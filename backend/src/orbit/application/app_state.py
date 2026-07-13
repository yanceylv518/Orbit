from __future__ import annotations

import math
import secrets
import threading
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from orbit.application.auth import hash_password, sanitize_user, verify_password
from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine, d, now_iso, q
from orbit.domain.strategy.regime import ensure_regime_gate_config


INITIAL_PRICES = {
    "BTCUSDT": Decimal("60000"),
    "ETHUSDT": Decimal("3400"),
    "SOLUSDT": Decimal("145"),
}

class AppState:
    @property
    def running(self) -> bool:
        return bool(self.runtime_state.get("running", False))

    @running.setter
    def running(self, value: bool) -> None:
        self.runtime_state["running"] = bool(value)

    def __init__(self, bootstrap: Any, config_path: str | None = None):
        self.root = Path(__file__).resolve().parents[4]
        self.config = load_config(config_path)
        self.lock = threading.RLock()
        self.mock_data_enabled = bool(self.config["runtime"].get("mock_data_enabled", False))
        self.runtime_state = {
            "running": bool(self.config["runtime"].get("auto_start", True)) and self.mock_data_enabled,
        }
        self.tick_index = 0
        self.price_history: dict[str, list[dict[str, Any]]] = {}
        self.strategy_events: list[dict[str, Any]] = []
        self.trade_events: list[dict[str, Any]] = []
        self.risk_events: list[dict[str, Any]] = []
        self.admin_audit_logs: list[dict[str, Any]] = []
        self.daily_reports: list[dict[str, Any]] = []
        self.binance_account_snapshots: dict[str, dict[str, Any]] = {}
        self.account_run_configs: list[dict[str, Any]] = []
        self.execution_plans: list[dict[str, Any]] = []
        self.metric_history: list[dict[str, Any]] = []
        self.symbol_metric_history: dict[str, list[dict[str, Any]]] = {}
        self.symbol_states: dict[str, dict[str, Any]] = {}
        self.store = bootstrap.create_state_store(self.root, self.config)
        self.sessions: dict[str, str] = {}
        self._load_directory_from_store()
        self.strategy = self.config["strategy_instances"][0]
        ensure_regime_gate_config(self.strategy)
        self.account_run_configs = deepcopy(self.config.get("account_run_configs", []))
        self.engine = EventEngine(self.strategy)
        if not self._restore_runtime():
            self._initialize_runtime()
        bootstrap.build_application_container(
            root=self.root,
            config=self.config,
            strategy=self.strategy,
            engine=self.engine,
            runtime_state=self.runtime_state,
            account_run_configs=self.account_run_configs,
            account_snapshots=self.binance_account_snapshots,
            symbol_states=self.symbol_states,
            execution_plans=self.execution_plans,
            audits=self.admin_audit_logs,
            strategy_events=self.strategy_events,
            trade_events=self.trade_events,
            risk_events=self.risk_events,
            reports=self.daily_reports,
            metric_history=self.metric_history,
            symbol_metric_history=self.symbol_metric_history,
            persist=self.persist,
            mock_data_enabled=self.mock_data_enabled,
        ).install(self)
        if self.mock_data_enabled and not self.metric_history:
            self.record_metric_snapshot()

    def _load_directory_from_store(self) -> None:
        loader = getattr(self.store, "load_directory", None)
        if not callable(loader):
            return
        directory = loader()
        if not directory:
            return
        self.config["users"] = directory.get("users", self.config.get("users", []))
        self.config["exchange_accounts"] = directory.get("exchange_accounts", self.config.get("exchange_accounts", []))
        self.config["strategy_instances"] = directory.get("strategy_instances", self.config.get("strategy_instances", []))
        self.config["account_run_configs"] = directory.get("account_run_configs", self.config.get("account_run_configs", []))

    def _initialize_runtime(self) -> None:
        self.symbol_states.clear()
        self.price_history.clear()
        if not self.mock_data_enabled:
            self.running = False
            return
        budgets = self.strategy["symbol_budget_usdt"]
        for symbol in self.strategy["symbols"]:
            price = INITIAL_PRICES.get(symbol, Decimal("100"))
            self.price_history[symbol] = [{"tick": 0, "price": float(price), "timestamp": now_iso()}]
            self.symbol_states[symbol] = self.engine.initialize_symbol(symbol, price, d(budgets[symbol]))
            self.symbol_metric_history[symbol] = []

    def _restore_runtime(self) -> bool:
        payload = self.store.load()
        if not payload:
            return False
        if not self.mock_data_enabled:
            self._restore_real_runtime(payload)
            return True
        runtime_strategy = payload.get("strategy_instance")
        if runtime_strategy and runtime_strategy.get("id") == self.strategy["id"]:
            for legacy_key in ("user_id", "exchange_account_id"):
                if legacy_key in self.strategy:
                    runtime_strategy[legacy_key] = self.strategy[legacy_key]
            self.strategy = runtime_strategy
            ensure_regime_gate_config(self.strategy)
            self.engine = EventEngine(self.strategy)
        symbol_states = payload.get("symbol_states")
        if not isinstance(symbol_states, dict):
            return False
        missing_symbols = [symbol for symbol in self.strategy["symbols"] if symbol not in symbol_states]
        if missing_symbols:
            return False
        self.tick_index = int(payload.get("tick_index", 0))
        self.running = bool(payload.get("running", self.running))
        self.symbol_states = symbol_states
        self.strategy_events = list(payload.get("strategy_events", []))
        self.trade_events = list(payload.get("trade_events", []))
        self.risk_events = list(payload.get("risk_events", []))
        self.admin_audit_logs = list(payload.get("admin_audit_logs", []))
        self.daily_reports = list(payload.get("daily_reports", []))
        self.binance_account_snapshots = dict(payload.get("binance_account_snapshots", {}))
        self.account_run_configs = list(payload.get("account_run_configs", self.account_run_configs))
        self.execution_plans = list(payload.get("execution_plans", []))[:300]
        self.metric_history = list(payload.get("metric_history", []))
        self.symbol_metric_history = dict(payload.get("symbol_metric_history", {}))
        self.price_history = dict(payload.get("price_history", {}))
        for symbol in self.strategy["symbols"]:
            if symbol not in self.price_history:
                price = d(self.symbol_states[symbol]["last_price"])
                self.price_history[symbol] = [{"tick": self.tick_index, "price": float(price), "timestamp": now_iso()}]
            if symbol not in self.symbol_metric_history:
                self.symbol_metric_history[symbol] = []
        return True

    def _restore_real_runtime(self, payload: dict[str, Any]) -> None:
        self.tick_index = 0
        self.running = False
        self.symbol_states = dict(payload.get("symbol_states", {}))
        self.strategy_events = []
        self.trade_events = []
        self.risk_events = []
        self.daily_reports = []
        self.metric_history = []
        self.symbol_metric_history = {}
        self.price_history = {}
        self.binance_account_snapshots = dict(payload.get("binance_account_snapshots", {}))
        self.account_run_configs = list(payload.get("account_run_configs", self.account_run_configs))
        self.execution_plans = list(payload.get("execution_plans", []))[:300]
        self.admin_audit_logs = [
            item for item in payload.get("admin_audit_logs", [])
            if item.get("action_type") == "SYNC_BINANCE_ACCOUNT"
        ][:60]

    def reset(self) -> dict[str, Any]:
        with self.lock:
            self.tick_index = 0
            self.event_history_repository.clear()
            self.audit_repository.clear()
            self.report_repository.clear()
            self.binance_account_snapshots.clear()
            self.execution_plans.clear()
            self.metric_repository.clear()
            self.symbol_states.clear()
            self.price_history.clear()
            self._initialize_runtime()
            if self.mock_data_enabled:
                self.record_metric_snapshot()
            self.persist()
            return self.snapshot()

    def set_running(self, running: bool, actor: str = "admin_001") -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.strategy_control_service.set_running(running, actor=actor)
            audit = result.pop("_audit")
            self.audit_service.record(**audit)
            uow.commit()
            return self.snapshot()

    def admin_emergency_stop(self, actor: str = "admin_001", reason: str | None = None) -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.strategy_control_service.emergency_stop(actor=actor, reason=reason)
            audit = result.pop("_audit")
            self.audit_service.record(**audit)
            uow.commit()
            return self.snapshot()

    def admin_resume(self, actor: str = "admin_001", reason: str | None = None) -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.strategy_control_service.resume(actor=actor, reason=reason)
            audit = result.pop("_audit")
            self.audit_service.record(**audit)
            uow.commit()
            return self.snapshot()

    def control_state(self) -> dict[str, Any]:
        return self.strategy_control_service.state()

    def validate_external_id(self, value: str, label: str) -> str:
        return self.account_service.validate_external_id(value, label)

    def is_admin_user_id(self, user_id: str) -> bool:
        return self.account_directory.is_admin_user_id(user_id)

    def upsert_business_user(self, incoming: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.account_service.upsert_business_user(
                    incoming,
                    actor=actor,
                    actor_user=self.user_by_id(actor),
                )
                audit = result.pop("_audit", None)
                if not result.get("ok"):
                    return result
                if audit:
                    self.audit_service.record(**audit)
                uow.commit()
                return result

    def upsert_exchange_account(self, incoming: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.account_service.upsert_exchange_account(
                    incoming,
                    actor=actor,
                    actor_user=self.user_by_id(actor),
                )
                audit = result.pop("_audit", None)
                invalidate_snapshot = result.pop("_invalidate_snapshot", None)
                reconcile_account_runtime = bool(result.pop("_reconcile_account_runtime", False))
                if not result.get("ok"):
                    return result
                if invalidate_snapshot:
                    self.account_snapshot_repository.delete(str(invalidate_snapshot))
                if reconcile_account_runtime:
                    self.run_config_service.ensure_all()
                if audit:
                    self.audit_service.record(**audit)
                uow.commit()
                return result

    def account_run_config(self, account_id: str) -> dict[str, Any] | None:
        return self.run_config_repository.get(account_id)

    def update_account_run_config(self, account_id: str, incoming: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.run_config_service.update(
                account_id,
                incoming,
                actor=actor,
                actor_user=self.user_by_id(actor),
            )
            audit = result.pop("_audit", None)
            if not result.get("ok"):
                return result
            new_plans = self.plan_refresh_service.refresh({account_id})
            if audit:
                self.audit_service.record(**audit)
            uow.commit()
            result["plans"] = deepcopy(new_plans)
            return result

    def authenticate(self, login: str, password: str) -> dict[str, Any]:
        login = login.strip()
        if not login or not password:
            return {"ok": False, "error": "请输入用户 ID/邮箱和密码。"}

        user = self.auth_user(login)
        if not user:
            return {"ok": False, "error": "用户不存在。"}
        if user.get("status", "active") != "active":
            return {"ok": False, "error": "用户已被禁用或暂停。"}

        password_ok = verify_password(password, user.get("password_salt"), user.get("password_hash"))
        if not password_ok and not user.get("password_hash") and self.bootstrap_password(user["id"]) == password:
            salt, password_hash = hash_password(password)
            setter = getattr(self.store, "set_user_password", None)
            if callable(setter):
                setter(user["id"], salt, password_hash)
            user["password_salt"] = salt
            user["password_hash"] = password_hash
            password_ok = True

        if not password_ok:
            return {"ok": False, "error": "密码错误。"}

        marker = getattr(self.store, "mark_user_login", None)
        if callable(marker):
            marker(user["id"])
        token = secrets.token_urlsafe(32)
        self.sessions[token] = user["id"]
        return {
            "ok": True,
            "session_token": token,
            "user": sanitize_user(user),
        }

    def logout(self, token: str | None) -> None:
        if token:
            self.sessions.pop(token, None)

    def current_user(self, token: str | None) -> dict[str, Any] | None:
        if not self.login_required() and not token:
            return self.default_operator_user()
        if not token:
            return None
        user_id = self.sessions.get(token)
        if not user_id and not self.login_required():
            return self.default_operator_user()
        if not user_id:
            return None
        user = self.user_by_id(user_id)
        if not user or user.get("status", "active") != "active":
            self.sessions.pop(token, None)
            if not self.login_required():
                return self.default_operator_user()
            return None
        return user

    def login_required(self) -> bool:
        return bool(self.config.get("auth", {}).get("login_required", False))

    def default_operator_user(self) -> dict[str, Any] | None:
        return self.account_directory.default_operator_user(
            self.config.get("auth", {}),
        )

    def auth_user(self, login: str) -> dict[str, Any] | None:
        auth_lookup = getattr(self.store, "auth_user", None)
        if callable(auth_lookup):
            user = auth_lookup(login)
            if user:
                return user
        return self.account_directory.auth_user(login)

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self.account_directory.user_by_id(user_id)

    def bootstrap_password(self, user_id: str) -> str | None:
        configured = self.config.get("auth", {}).get("bootstrap_passwords", {})
        if user_id in configured:
            return configured[user_id]
        defaults = {
            "admin_001": "admin123456",
            "user_001": "user123456",
        }
        return defaults.get(user_id)

    def update_event_config(self, incoming: dict[str, Any], actor: str = "admin_001") -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.strategy_config_service.update(incoming, actor=actor)
            audit = result.pop("_audit")
            self.engine = result["engine"]
            self.symbol_state_service.engine = self.engine
            self.audit_service.record(**audit)
            uow.commit()
            return self.snapshot()

    def tick_once(self) -> dict[str, Any]:
        if not self.mock_data_enabled:
            return self.snapshot()
        with self.lock:
            self.tick_index += 1
            for symbol in self.strategy["symbols"]:
                price = self.next_price(symbol, self.tick_index)
                state, events, risks = self.engine.on_tick(self.symbol_states[symbol], price)
                self.symbol_states[symbol] = state
                self.price_history[symbol].append({"tick": self.tick_index, "price": float(price), "timestamp": now_iso()})
                self.price_history[symbol] = self.price_history[symbol][-160:]
                self.runtime_event_service.record_engine_results(events, risks)
            self.record_metric_snapshot()
            persist_payload = self.persist_payload()
            snapshot = self.snapshot()
        self.store.save(persist_payload)
        return snapshot

    def generate_daily_report(self, actor: str = "admin_001") -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.daily_report_service.generate(
                self.snapshot(include_internal_history=True),
                actor=actor,
            )
            audit = result.pop("_audit", None)
            if audit:
                self.audit_service.record(**audit)
            uow.commit()
            report = result["report"]
            snapshot = self.snapshot()
            snapshot["generated_report"] = report
            return snapshot

    def sync_binance_account(self, account_id: str, actor: str = "system") -> dict[str, Any]:
        fetched = self.account_sync_service.fetch(
            account_id,
            actor=actor,
            actor_user=self.user_by_id(actor) if actor != "system" else None,
        )
        if not fetched.get("ok"):
            return fetched

        with self.lock, self.app_uow as uow:
            result = self.account_sync_service.apply(fetched, actor=actor)
            audit = result.pop("_audit", None)
            if not result.get("ok"):
                return result
            if audit:
                self.audit_service.record(**audit)
            uow.commit()
            return result["snapshot"]

    def update_binance_credentials(
        self,
        account_id: str,
        actor: str,
        api_key: str,
        api_secret: str,
    ) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.credential_service.update_binance_credentials(
                    account_id=account_id,
                    actor=actor,
                    actor_user=self.user_by_id(actor),
                    api_key=api_key,
                    api_secret=api_secret,
                )
                audit = result.pop("_audit", None)
                invalidate_snapshot = result.pop("_invalidate_snapshot", None)
                if not result.get("ok"):
                    return result
                if invalidate_snapshot:
                    self.account_snapshot_repository.delete(str(invalidate_snapshot))
                if audit:
                    self.audit_service.record(**audit)
                uow.commit()
                return result

    def account_by_id(self, account_id: str) -> dict[str, Any] | None:
        return self.account_directory.account_by_id(account_id)

    def actor_can_access_account(self, actor: str, account_id: str) -> bool:
        actor_user = self.user_by_id(actor)
        return self.account_directory.can_access_account(actor_user, account_id)

    def user_can_access_account(self, user: dict[str, Any], account_id: str) -> bool:
        return self.account_directory.can_access_account(user, account_id)

    def user_can_operate_account(self, user: dict[str, Any], account_id: str) -> bool:
        return self.account_directory.can_operate_account(user, account_id)

    def execution_plan_by_id(self, plan_id: str) -> dict[str, Any] | None:
        return self.execution_plan_repository.get(plan_id)

    def generate_execution_plans(self, account_id: str | None = None, actor: str = "system") -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                if account_id and not self.account_by_id(account_id):
                    return {"ok": False, "error": f"账户不存在：{account_id}"}
                account_ids = {account_id} if account_id else {account["id"] for account in self.config.get("exchange_accounts", [])}
                plans = self.plan_refresh_service.refresh(account_ids)
                self.audit_service.record(
                    actor=actor,
                    action_type="GENERATE_EXECUTION_PLANS",
                    reason="生成第一阶段执行计划，仅用于实盘前演练，不会下单。",
                    after_value={
                        "account_ids": sorted(account_ids),
                        "plan_count": len(plans),
                    },
                )
                uow.commit()
                return {"ok": True, "plans": deepcopy(plans)}

    def confirm_execution_plan(self, plan_id: str, actor: str, note: str | None = None) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.execution_plan_service.confirm(
                    plan_id=plan_id,
                    actor=actor,
                    actor_user=self.user_by_id(actor),
                    note=note,
                )
                audit = result.pop("_audit", None)
                if not result.get("ok"):
                    return result
                if audit:
                    self.audit_service.record(**audit)
                uow.commit()
                return result

    def execute_live_plan(self, plan_id: str, actor: str, confirm_phrase: str) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.order_execution_service.execute(
                    plan_id=plan_id,
                    actor=actor,
                    actor_user=self.user_by_id(actor),
                    confirm_phrase=confirm_phrase,
                )
                audit = result.pop("_audit", None)
                if audit:
                    # 无论成败都留审计：live 执行的每一次尝试都必须可追溯
                    self.audit_service.record(**audit)
                uow.commit()
                return result

    def record_execution_plan_export(self, plan_ids: list[Any], actor: str) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.execution_plan_service.record_export(
                    plan_ids=plan_ids,
                    actor=actor,
                    actor_user=self.user_by_id(actor),
                )
                audit = result.pop("_audit", None)
                if not result.get("ok"):
                    return result
                if audit:
                    self.audit_service.record(**audit)
                uow.commit()
                return result

    def next_price(self, symbol: str, tick: int) -> Decimal:
        base = INITIAL_PRICES.get(symbol, Decimal("100"))
        if symbol == "BTCUSDT":
            move = Decimal(str(0.0036 * tick + 0.009 * math.sin(tick / 2.0)))
        elif symbol == "ETHUSDT":
            move = Decimal(str(0.010 * math.sin(tick / 2.7) + 0.0008 * tick))
        elif symbol == "SOLUSDT":
            move = Decimal(str(-0.0025 * tick + 0.011 * math.sin(tick / 2.2)))
        else:
            move = Decimal(str(0.005 * math.sin(tick / 2.0)))
        return q(base * (Decimal("1") + move), Decimal("0.000000000001"))

    def background_loop(self) -> None:
        interval = float(self.config["runtime"].get("tick_interval_seconds", 3))
        feed_config = self.config["runtime"].get("market_feed", {})
        poll_seconds = max(5.0, float(feed_config.get("poll_seconds", 30)))
        last_poll = 0.0
        while True:
            if self.running and self.mock_data_enabled:
                self.tick_once()
            if not self.mock_data_enabled and time.time() - last_poll >= poll_seconds:
                last_poll = time.time()
                self.market_tick_once()
            time.sleep(interval if self.mock_data_enabled else 1)

    def market_tick_once(self) -> dict[str, Any]:
        """真实模式行情 tick：锁外拉 K 线，锁内推进生命周期并重建计划。"""
        service = getattr(self, "market_feed_service", None)
        if service is None or self.mock_data_enabled or not service.status.get("enabled"):
            return {"ticks": 0}
        try:
            klines_by_symbol = service.poll()  # 网络 I/O，锁外
        except Exception as exc:
            service.status["last_error"] = str(exc)
            return {"ticks": 0, "error": str(exc)}
        if not klines_by_symbol:
            return {"ticks": 0}
        with self.lock:
            result = service.apply(klines_by_symbol)
            if result["changed_account_ids"]:
                changed = set(result["changed_account_ids"])
                paper_service = getattr(self, "paper_execution_service", None)
                if paper_service is not None:
                    result["paper"] = paper_service.on_market_tick(changed)
                self.plan_refresh_service.refresh_from_states(changed)
                self.persist()
        return result

    def start_background(self) -> None:
        thread = threading.Thread(target=self.background_loop, name="orbit-runner", daemon=True)
        thread.start()

    def persist(self) -> None:
        self.store.save(self.persist_payload())

    def persist_payload(self) -> dict[str, Any]:
        symbol_views = {}
        for symbol, state in self.symbol_states.items():
            symbol_views[symbol] = self.portfolio_views.symbol_view(symbol, state)
        return {
            "tick_index": self.tick_index,
            "running": self.running,
            "users": deepcopy(self.config["users"]),
            "exchange_accounts": deepcopy(self.config["exchange_accounts"]),
            "account_run_configs": deepcopy(self.run_config_repository.all()),
            "strategy_instance": deepcopy(self.strategy),
            "symbol_states": deepcopy(self.symbol_states),
            "symbol_views": symbol_views,
            "strategy_events": deepcopy(self.event_history_repository.strategy_events()),
            "trade_events": deepcopy(self.event_history_repository.trade_events()),
            "risk_events": deepcopy(self.event_history_repository.risk_events()),
            "admin_audit_logs": deepcopy(self.admin_audit_logs),
            "daily_reports": deepcopy(self.report_repository.all()),
            "binance_account_snapshots": deepcopy(self.account_snapshot_repository.all()),
            "execution_plans": deepcopy(self.execution_plans),
            "price_history": deepcopy(self.price_history),
            "metric_history": deepcopy(self.metric_repository.all()),
            "symbol_metric_history": deepcopy(self.metric_repository.by_symbol()),
            "updated_at": now_iso(),
        }

    def public_snapshot(self) -> dict[str, Any]:
        return self.snapshot_queries.public_snapshot()

    def snapshot(
        self,
        current_user: dict[str, Any] | None = None,
        include_internal_history: bool = False,
    ) -> dict[str, Any]:
        with self.lock:
            return self.snapshot_queries.snapshot(
                running=self.running,
                tick_index=self.tick_index,
                symbol_states=self.symbol_states,
                price_history=self.price_history,
                current_user=current_user,
                include_internal_history=include_internal_history,
                market_feed=self.runtime_state.get("market_feed"),
            )

    def sanitize_account(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.account_directory.sanitize_account(account)

    def record_metric_snapshot(self) -> None:
        symbols = [self.portfolio_views.symbol_view(symbol, state) for symbol, state in self.symbol_states.items()]
        totals = self.portfolio_views.totals(symbols)
        self.metric_service.record(tick=self.tick_index, symbols=symbols, totals=totals)
