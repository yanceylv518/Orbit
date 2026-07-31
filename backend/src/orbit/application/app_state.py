from __future__ import annotations

import math
import hashlib
import json
import secrets
import subprocess
import threading
import time
import urllib.request
from copy import deepcopy
from decimal import Decimal, ROUND_UP
from pathlib import Path
from typing import Any

from orbit.application.auth import hash_password, sanitize_user, verify_password
from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine, d, now_iso, q
from orbit.domain.strategy.regime import ensure_regime_gate_config
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC
from orbit.application.live_pilot_control import (
    LIVE_ACTIVATION_PHRASE,
    normalize_live_pilot_control,
    project_preflight,
    validate_epoch,
)
from orbit.application.trend_execution_checklist import build_tb4_exchange_rules
from orbit.application.trend_forward import TrendForwardService
from orbit.application.trend_forward_market import TrendForwardMarketDriver
from orbit.infrastructure.exchange.binance import BinanceFuturesClient
from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed
from orbit.infrastructure.persistence.trend_forward_ledger import TrendForwardLedger


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
        self.live_pilot_control = normalize_live_pilot_control(
            None, self.config.get("runtime", {}),
        )
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
            live_pilot_control=self.live_pilot_control,
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
        if getattr(self.store, "directory_authoritative", False):
            users = list(directory.get("users") or [])
            accounts = list(directory.get("exchange_accounts") or [])
            strategies = list(directory.get("strategy_instances") or [])
            admins = [
                user for user in users
                if user.get("role") in {"admin", "super_admin"}
                and user.get("status", "active") == "active"
            ]
            missing = []
            if not users:
                missing.append("users")
            if not accounts:
                missing.append("exchange_accounts")
            if not strategies:
                missing.append("strategy_instances")
            if missing:
                raise RuntimeError(
                    "MySQL directory is incomplete: "
                    + ", ".join(missing)
                    + ". Run backend/scripts/migrate_config_directory_to_mysql.py "
                      "before starting Orbit."
                )
            if self.config.get("auth", {}).get("login_required", False) and not admins:
                raise RuntimeError(
                    "MySQL directory has no active administrator. "
                    "Run backend/scripts/migrate_config_directory_to_mysql.py "
                    "with a valid administrator before starting Orbit."
                )
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
        self.live_pilot_control = normalize_live_pilot_control(
            payload.get("live_pilot_control"),
            self.config.get("runtime", {}),
        )
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
            if item.get("action_type") in {"SYNC_BINANCE_ACCOUNT", "RESUME_STOPPED_SYMBOL"}
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

    def resume_stopped_symbol(
        self,
        account_id: str,
        symbol: str,
        *,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        with self.lock, self.app_uow as uow:
            result = self.symbol_recovery_service.resume_stopped_symbol(
                account_id,
                symbol,
                actor=actor,
                actor_user=self.user_by_id(actor),
                reason=reason,
            )
            audit = result.pop("_audit", None)
            if not result.get("ok"):
                return result
            if audit:
                self.audit_service.record(**audit)
            uow.commit()
            return result

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
        if user.get("role") not in {"admin", "super_admin"}:
            return {"ok": False, "error": "该账号不是平台管理员，不能登录控制台。"}

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
        if getattr(self.store, "directory_authoritative", False):
            return None
        configured = self.config.get("auth", {}).get("bootstrap_passwords", {})
        return configured.get(user_id)

    def health(self) -> dict[str, Any]:
        checker = getattr(self.store, "health_check", None)
        try:
            storage = checker() if callable(checker) else {"ok": True, "driver": "unknown"}
        except Exception:
            storage = {
                "ok": False,
                "driver": self.config.get("storage", {}).get("driver", "unknown"),
                "error": "storage_unavailable",
            }
        return {
            "ok": bool(storage.get("ok")),
            "service": "orbit",
            "storage": storage,
        }

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

        with self.lock:
            with self.app_uow as uow:
                result = self.account_sync_service.apply(fetched, actor=actor)
                audit = result.pop("_audit", None)
                if not result.get("ok"):
                    return result
                if audit:
                    self.audit_service.record(**audit)
                uow.commit()
                snapshot = result["snapshot"]
            reconciliation = self.live_reconciliation_service.record_snapshot(
                account_id, snapshot,
            )
            return deepcopy(snapshot) | {"live_reconciliation_record": reconciliation}

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

    def configure_live_pilot(self, *, actor: str, account_id: str) -> dict[str, Any]:
        if self.live_pilot_control.get("auto_execution_enabled"):
            return {"ok": False, "error": "自动执行运行中，请先急停后再修改专用账户。"}
        account_id = str(account_id or "").strip()
        account = self.account_by_id(account_id)
        if not account:
            return {"ok": False, "error": "请选择一个已存在的 Binance 合约账户。"}
        before = deepcopy(self.live_pilot_control)
        with self.lock:
            self.live_pilot_control.update({
                "version": int(self.live_pilot_control.get("version") or 1) + 1,
                "status": "CONFIGURED",
                "live_account_id": account_id,
                "auto_execution_enabled": False,
                "execution_epoch": "",
                "last_preflight": None,
                "updated_at": now_iso(),
                "updated_by": actor,
            })
            self.live_reconciliation_service.configure(
                live_account_id=account_id,
                quantity_tolerance_pct=float(
                    self.live_pilot_control.get("quantity_tolerance_pct", 1.0)
                ),
            )
            self.live_execution_service.configure(
                enabled=False,
                execution_epoch="",
                live_account_id=account_id,
            )
            self.audit_service.record(
                actor=actor,
                action_type="CONFIGURE_LIVE_PILOT",
                reason="通过实盘启用向导选择专用 Binance 主网账户。",
                before_value=before,
                after_value=deepcopy(self.live_pilot_control),
            )
            self.persist()
        return {"ok": True, "control": deepcopy(self.live_pilot_control)}

    def prepare_live_pilot_account(
        self,
        *,
        actor: str,
        account_id: str,
        confirmation: str,
    ) -> dict[str, Any]:
        if self.live_pilot_control.get("auto_execution_enabled"):
            return {"ok": False, "error": "自动执行运行中，不能重新准备账户。"}
        if str(confirmation or "").strip() != "PREPARE LIVE ACCOUNT":
            return {"ok": False, "error": "确认短语不正确。"}
        account = self.account_by_id(str(account_id or "").strip())
        if not account:
            return {"ok": False, "error": "账户不存在。"}
        candidate_account = deepcopy(account)
        candidate_account["testnet"] = False
        exchange_result: dict[str, Any] = {
            "position_mode": "ONE_WAY",
            "leverage": {},
        }
        try:
            client = BinanceFuturesClient.from_account(
                candidate_account,
                self.credential_vault,
            )
            open_orders = client.open_orders()
            if open_orders:
                return {
                    "ok": False,
                    "error": "账户存在未完成挂单，请先在 Binance 处理后再准备。",
                    "open_order_count": len(open_orders),
                }
            positions = client.position_risk()
            nonzero_positions = [
                str(item.get("symbol") or "")
                for item in positions
                if Decimal(str(item.get("positionAmt") or 0)) != 0
            ]
            if nonzero_positions:
                return {
                    "ok": False,
                    "error": "账户存在持仓，不能自动切换持仓模式。",
                    "position_symbols": nonzero_positions,
                }
            if bool(client.position_mode().get("dualSidePosition")):
                client.change_position_mode(dual_side=False)
            for symbol in TB4_SPEC.symbols:
                response = client.change_leverage(symbol, 1)
                applied_leverage = int(response.get("leverage") or 0)
                if applied_leverage != 1:
                    raise RuntimeError(
                        f"{symbol} 杠杆设置返回异常：{applied_leverage}x。"
                    )
                exchange_result["leverage"][symbol] = applied_leverage
            wrong_leverage: list[str] = []
            for attempt in range(3):
                verified_positions = {
                    str(item.get("symbol") or ""): item
                    for item in client.position_risk()
                }
                wrong_leverage = [
                    symbol
                    for symbol in TB4_SPEC.symbols
                    if str(
                        (verified_positions.get(symbol) or {}).get("leverage")
                        or ""
                    ) != "1"
                ]
                if not wrong_leverage:
                    break
                if attempt < 2:
                    time.sleep(0.5)
            if wrong_leverage:
                raise RuntimeError(
                    "以下市场的 1x 杠杆设置未通过回读验证："
                    + ", ".join(wrong_leverage)
                )
        except Exception as exc:
            with self.lock:
                self.audit_service.record(
                    actor=actor,
                    action_type="PREPARE_LIVE_PILOT_ACCOUNT_FAILED",
                    reason="Binance 主网账户准备失败。",
                    after_value={
                        "account_id": account["id"],
                        "error": str(exc),
                    },
                )
                self.persist()
            return {"ok": False, "error": f"Binance 账户准备失败：{exc}"}
        with self.lock, self.app_uow as uow:
            if self.live_pilot_control.get("auto_execution_enabled"):
                return {"ok": False, "error": "自动执行已由另一个请求启用。"}
            before_control = deepcopy(self.live_pilot_control)
            result = self.account_service.upsert_exchange_account(
                {
                    "account_id": account["id"],
                    "user_id": account["user_id"],
                    "account_label": account.get("account_label") or account["id"],
                    "status": account.get("status", "active"),
                    "testnet": False,
                    "dry_run": False,
                    "hedge_mode_required": False,
                },
                actor=actor,
                actor_user=self.user_by_id(actor),
            )
            if not result.get("ok"):
                return result
            audit = result.pop("_audit", None)
            invalidate = result.pop("_invalidate_snapshot", None)
            if invalidate:
                self.account_snapshot_repository.delete(str(invalidate))
            if audit:
                audit["action_type"] = "PREPARE_LIVE_PILOT_ACCOUNT"
                audit["reason"] = "管理员确认将账户切换为 Binance 主网实盘、单向持仓要求。"
                self.audit_service.record(**audit)
            self.live_pilot_control.update({
                "version": int(self.live_pilot_control.get("version") or 1) + 1,
                "status": "CONFIGURED",
                "last_preflight": None,
                "updated_at": now_iso(),
                "updated_by": actor,
            })
            self.audit_service.record(
                actor=actor,
                action_type="INVALIDATE_LIVE_PILOT_PREFLIGHT",
                reason="实盘账户属性已改变，原生产预检失效。",
                before_value=before_control,
                after_value=deepcopy(self.live_pilot_control),
            )
            uow.commit()
        self.persist()
        return {
            "ok": True,
            "account": self.sanitize_account(account),
            "exchange": exchange_result,
        }

    def initialize_trend_forward(self, *, actor: str) -> dict[str, Any]:
        if self.live_pilot_control.get("auto_execution_enabled"):
            return {"ok": False, "error": "自动执行已启用，不能重新初始化前向账本。"}
        data_dir = self._trend_data_dir()
        ledger = TrendForwardLedger(data_dir)
        existing = ledger.manifest()
        if existing:
            return {
                "ok": True,
                "already_initialized": True,
                "manifest_sha256": existing["manifest_sha256"],
            }
        protocol_path = self.root / "docs" / "design" / "TB4_FORWARD.md"
        protocol_sha256 = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
        code_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.root, text=True,
        ).strip()
        service = TrendForwardService(ledger, self.trend_checklist_projector)
        driver = TrendForwardMarketDriver(
            BinanceKlineFeed(base_url="https://fapi.binance.com"),
            service,
        )
        snapshot = driver.initialize(
            code_commit=code_commit,
            protocol_sha256=protocol_sha256,
        )
        with self.lock:
            before = deepcopy(self.live_pilot_control)
            self.live_pilot_control.update({
                "version": int(self.live_pilot_control.get("version") or 1) + 1,
                "status": (
                    "CONFIGURED"
                    if self.live_pilot_control.get("live_account_id")
                    else "FORWARD_READY"
                ),
                "forward_enabled": True,
                "updated_at": now_iso(),
                "updated_by": actor,
            })
            self.trend_forward_cache_invalidate()
            self.audit_service.record(
                actor=actor,
                action_type="INITIALIZE_TB4_FORWARD",
                reason="管理员通过实盘启用向导原子初始化 TB4 不可变前向账本。",
                before_value=before,
                after_value={
                    "manifest_sha256": snapshot["manifest_sha256"],
                    "control": deepcopy(self.live_pilot_control),
                },
            )
            self.persist()
        return {
            "ok": True,
            "already_initialized": False,
            "manifest_sha256": snapshot["manifest_sha256"],
        }

    def refresh_live_exchange_rules(self, *, actor: str) -> dict[str, Any]:
        source = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        with urllib.request.urlopen(source, timeout=30) as response:
            exchange_info = json.loads(response.read().decode("utf-8"))
        fetched_at = now_iso().replace("+00:00", "Z")
        rules = build_tb4_exchange_rules(
            exchange_info,
            fetched_at=fetched_at,
            source=source,
            refresh_after_days=30,
        )
        path = self._trend_rules_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        with self.lock:
            before = deepcopy(self.live_pilot_control)
            self.trend_checklist_projector.exchange_rules = deepcopy(rules)
            self.trend_forward_cache_invalidate()
            self.live_pilot_control.update({
                "version": int(self.live_pilot_control.get("version") or 1) + 1,
                "status": (
                    "CONFIGURED"
                    if self.live_pilot_control.get("live_account_id")
                    else self.live_pilot_control.get("status", "DRAFT")
                ),
                "rules_fetched_at": fetched_at,
                "last_preflight": None,
                "updated_at": now_iso(),
                "updated_by": actor,
            })
            self.audit_service.record(
                actor=actor,
                action_type="REFRESH_TB4_EXCHANGE_RULES",
                reason="管理员通过实盘启用向导刷新 Binance 主网交易规则。",
                before_value=before,
                after_value={"rules_fetched_at": fetched_at, "path": str(path)},
            )
            self.persist()
        return {"ok": True, "rules_fetched_at": fetched_at}

    def run_live_pilot_preflight(self, *, actor: str) -> dict[str, Any]:
        account_id = str(self.live_pilot_control.get("live_account_id") or "")
        account = self.account_by_id(account_id)
        checks: list[dict[str, Any]] = []

        def check(
            code: str,
            ok: bool,
            message: str,
            detail: Any = None,
            *,
            required: bool = True,
        ) -> None:
            item = {
                "code": code,
                "ok": bool(ok),
                "required": bool(required),
                "message": message,
            }
            if detail is not None:
                item["detail"] = detail
            checks.append(item)

        check("ACCOUNT_SELECTED", bool(account), "已选择专用交易账户" if account else "尚未选择交易账户")
        if not account:
            result = project_preflight(checks)
            self._record_live_preflight(actor, result)
            return result
        check("MAINNET", not bool(account.get("testnet")), "账户使用 Binance 主网")
        check("LIVE_MODE", not bool(account.get("dry_run", True)), "账户已解除只读模式")
        check("ACCOUNT_ACTIVE", account.get("status") == "active", "账户状态正常")

        snapshot = self.sync_binance_account(account_id, actor=actor)
        check(
            "ACCOUNT_SYNC",
            snapshot.get("status") == "synced",
            "账户同步成功" if snapshot.get("status") == "synced" else "账户同步失败",
            snapshot.get("error"),
        )
        if snapshot.get("status") == "synced":
            dual = bool((snapshot.get("position_mode") or {}).get("dual_side_position"))
            check("ONE_WAY_MODE", not dual, "Binance 实际持仓模式为单向")
            equity = float(snapshot.get("total_wallet_balance") or 0)
            required = float(self.live_pilot_control.get("live_capital_usdt", 500))
            check(
                "CAPITAL",
                equity >= required,
                f"合约钱包权益不少于 {required:.2f} USDT",
                {"equity_usdt": equity, "required_usdt": required},
            )

        forward = self.trend_forward_snapshot()
        checklist = forward.get("execution_checklist") or {}
        check("FORWARD_INITIALIZED", forward.get("status") != "NOT_STARTED", "TB4 前向账本已初始化")
        checklist_ready = checklist.get("status") == "READY"
        check(
            "CHECKLIST_READY",
            checklist_ready,
            (
                "冻结执行清单已就绪"
                if checklist_ready
                else "等待首根有效 4h 收盘后自动生成冻结执行清单"
            ),
            {"status": checklist.get("status") or "NOT_AVAILABLE"},
            required=False,
        )
        check("RULES_FRESH", not bool(checklist.get("rules_stale")), "Binance 交易规则未过期")

        try:
            client = BinanceFuturesClient.from_account(account, self.credential_vault)
            open_orders = client.open_orders()
            check("NO_OPEN_ORDERS", not open_orders, "账户没有未完成挂单", {"count": len(open_orders)})
            positions = client.position_risk()
            position_map = {str(item.get("symbol")): item for item in positions}
            nonzero = [
                symbol for symbol, item in position_map.items()
                if symbol in TB4_SPEC.symbols and Decimal(str(item.get("positionAmt") or 0)) != 0
            ]
            check("NO_POSITIONS", not nonzero, "12 个策略市场没有既有持仓", nonzero)
            wrong_leverage = [
                symbol for symbol in TB4_SPEC.symbols
                if str((position_map.get(symbol) or {}).get("leverage") or "") != "1"
            ]
            check("LEVERAGE_1X", not wrong_leverage, "12 个策略市场杠杆均为 1x", wrong_leverage)
            test_params = self._live_permission_test_order(client, checklist)
            client.test_order(test_params)
            check(
                "TRADE_PERMISSION",
                True,
                "Binance 合约交易权限测试通过",
                {
                    "symbol": test_params["symbol"],
                    "quantity": test_params["quantity"],
                    "order_sent": False,
                },
            )
        except Exception as exc:
            check("EXCHANGE_PREFLIGHT", False, "Binance 实盘预检请求失败", str(exc))

        result = project_preflight(checks)
        self._record_live_preflight(actor, result)
        return result

    def _live_permission_test_order(
        self,
        client: BinanceFuturesClient,
        checklist: dict[str, Any],
    ) -> dict[str, Any]:
        executable = next(
            (
                row
                for row in checklist.get("rows") or []
                if row.get("status") == "EXECUTABLE"
            ),
            None,
        )
        if executable:
            symbol = str(executable["symbol"])
            quantity = Decimal(str(executable["target_quantity"])).copy_abs()
        else:
            symbol = TB4_SPEC.symbols[0]
            rules = (
                self.trend_checklist_projector.exchange_rules.get("symbols") or {}
            ).get(symbol)
            if not rules:
                raise RuntimeError(f"{symbol} 交易规则尚未加载。")
            price = Decimal(str(client.ticker_price(symbol)["price"]))
            step_size = Decimal(str(rules["quantity_step"]))
            min_quantity = Decimal(str(rules["min_quantity"]))
            min_notional = Decimal(str(rules["min_notional_usdt"]))
            raw_quantity = max(
                min_quantity,
                min_notional * Decimal("1.10") / price,
            )
            quantity = (
                raw_quantity / step_size
            ).to_integral_value(rounding=ROUND_UP) * step_size
        return {
            "symbol": symbol,
            "side": "BUY",
            "positionSide": "BOTH",
            "type": "MARKET",
            "quantity": format(quantity, "f"),
        }

    def activate_live_pilot(
        self,
        *,
        actor: str,
        execution_epoch: str,
        confirmation: str,
    ) -> dict[str, Any]:
        if self.live_pilot_control.get("auto_execution_enabled"):
            return {"ok": False, "error": "自动执行已经启用，不能覆盖当前执行批次。"}
        if str(confirmation or "").strip() != LIVE_ACTIVATION_PHRASE:
            return {"ok": False, "error": "启用确认短语不正确。"}
        try:
            epoch = validate_epoch(execution_epoch)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        if any(
            item["payload"].get("execution_epoch") == epoch
            for item in self.live_execution_service.execution_ledger.read_all()
        ):
            return {"ok": False, "error": "该执行批次已经使用，不能重复启用。"}
        preflight = self.run_live_pilot_preflight(actor=actor)
        if not preflight["passed"]:
            return {"ok": False, "error": "实盘预检未全部通过。", "preflight": preflight}
        checklist_ready = any(
            item.get("code") == "CHECKLIST_READY" and item.get("ok")
            for item in preflight.get("checks") or []
        )
        activation_status = "ACTIVE" if checklist_ready else "ARMED"
        with self.lock:
            if self.live_pilot_control.get("auto_execution_enabled"):
                return {"ok": False, "error": "自动执行已经由另一个请求启用。"}
            before = deepcopy(self.live_pilot_control)
            self.live_execution_service.configure(
                enabled=True,
                execution_epoch=epoch,
                live_account_id=str(self.live_pilot_control["live_account_id"]),
                max_snapshot_age_seconds=int(
                    self.live_pilot_control["max_snapshot_age_seconds"]
                ),
                max_order_notional_usdt=float(
                    self.live_pilot_control["max_order_notional_usdt"]
                ),
                round_gross_multiplier=float(
                    self.live_pilot_control["round_gross_multiplier"]
                ),
            )
            try:
                self.live_pilot_control.update({
                    "version": int(self.live_pilot_control.get("version") or 1) + 1,
                    "status": activation_status,
                    "forward_enabled": True,
                    "auto_execution_enabled": True,
                    "execution_epoch": epoch,
                    "updated_at": now_iso(),
                    "updated_by": actor,
                })
                self.audit_service.record(
                    actor=actor,
                    action_type="ACTIVATE_LIVE_PILOT",
                    reason="管理员通过双重确认授权并布防 LIVE-SMALL 自动执行。",
                    before_value=before,
                    after_value=deepcopy(self.live_pilot_control),
                )
                self.persist()
            except Exception:
                self.live_pilot_control = before
                self.live_execution_service.configure(
                    enabled=False,
                    execution_epoch=epoch,
                    live_account_id=str(before.get("live_account_id") or ""),
                )
                raise
        return {
            "ok": True,
            "status": activation_status,
            "execution_epoch": epoch,
        }

    def _record_live_preflight(self, actor: str, result: dict[str, Any]) -> None:
        with self.lock:
            before = deepcopy(self.live_pilot_control)
            control_status = (
                str(self.live_pilot_control.get("status") or "ACTIVE")
                if self.live_pilot_control.get("auto_execution_enabled")
                else ("PREFLIGHT_READY" if result["passed"] else "CONFIGURED")
            )
            self.live_pilot_control.update({
                "version": int(self.live_pilot_control.get("version") or 1) + 1,
                "status": control_status,
                "last_preflight": deepcopy(result),
                "updated_at": now_iso(),
                "updated_by": actor,
            })
            self.audit_service.record(
                actor=actor,
                action_type="RUN_LIVE_PILOT_PREFLIGHT",
                reason="管理员运行小资金实盘生产预检。",
                before_value=before,
                after_value={"status": result["status"], "checks": result["checks"]},
            )
            self.persist()

    def _trend_data_dir(self) -> Path:
        value = str(
            self.config.get("runtime", {}).get("trend_forward", {}).get(
                "data_dir", "var/forward/tb4",
            )
        )
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def _trend_rules_path(self) -> Path:
        value = str(
            self.config.get("runtime", {}).get("trend_forward", {}).get(
                "exchange_rules_path",
                "var/forward/live-small/tb4_exchange_rules.json",
            )
            or "var/forward/live-small/tb4_exchange_rules.json"
        )
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def emergency_stop_live_execution(self, *, actor: str, reason: str) -> dict[str, Any]:
        with self.lock:
            with self.app_uow as uow:
                result = self.live_execution_service.emergency_stop(
                    actor=actor,
                    reason=reason,
                )
                if not result.get("ok"):
                    return result
                self.audit_service.record(
                    actor=actor,
                    action_type="EMERGENCY_STOP_LIVE_EXECUTION",
                    reason=reason,
                    after_value={
                        "execution_epoch": self.live_execution_service.execution_epoch,
                        "account_id": self.live_execution_service.live_account_id,
                        "status": result["status"],
                    },
                )
                self.live_pilot_control.update({
                    "version": int(self.live_pilot_control.get("version") or 1) + 1,
                    "status": "STOPPED",
                    "auto_execution_enabled": False,
                    "updated_at": now_iso(),
                    "updated_by": actor,
                })
                self.live_execution_service.enabled = False
                uow.commit()
            self.persist()
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
        trend_config = self.config["runtime"].get("trend_forward", {})
        trend_poll_seconds = max(10.0, float(trend_config.get("poll_seconds", 60)))
        last_trend_poll = 0.0
        while True:
            if self.running and self.mock_data_enabled:
                self.tick_once()
            if not self.mock_data_enabled and time.time() - last_poll >= poll_seconds:
                last_poll = time.time()
                self.market_tick_once()
            if (
                not self.mock_data_enabled
                and bool(self.live_pilot_control.get("forward_enabled", False))
                and time.time() - last_trend_poll >= trend_poll_seconds
            ):
                last_trend_poll = time.time()
                self.trend_forward_tick_once()
            time.sleep(interval if self.mock_data_enabled else 1)

    def trend_forward_tick_once(self) -> dict[str, Any]:
        """Single-writer TB4 poll followed by idempotent LIVE-SMALL execution."""
        try:
            result = self.trend_forward_poll()
        except Exception as exc:
            return {"ticks": 0, "error": str(exc), "live_execution": None}
        execution = self.live_execution_service.execute_due(
            lambda account_id: self.sync_binance_account(account_id, actor="system")
        )
        checklist = self.trend_forward_snapshot().get("execution_checklist") or {}
        if (
            self.live_pilot_control.get("status") == "ARMED"
            and checklist.get("status") == "READY"
        ):
            with self.lock:
                if self.live_pilot_control.get("status") == "ARMED":
                    before = deepcopy(self.live_pilot_control)
                    self.live_pilot_control.update({
                        "version": int(
                            self.live_pilot_control.get("version") or 1
                        ) + 1,
                        "status": "ACTIVE",
                        "updated_at": now_iso(),
                        "updated_by": "system",
                    })
                    self.audit_service.record(
                        actor="system",
                        action_type="LIVE_PILOT_FIRST_CHECKLIST_READY",
                        reason="首份冻结执行清单已就绪，实盘批次进入逐轮自动执行状态。",
                        before_value=before,
                        after_value=deepcopy(self.live_pilot_control),
                    )
                    self.persist()
        return result | {"live_execution": execution}

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
            "live_pilot_control": deepcopy(self.live_pilot_control),
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
            payload = self.snapshot_queries.snapshot(
                running=self.running,
                tick_index=self.tick_index,
                symbol_states=self.symbol_states,
                price_history=self.price_history,
                current_user=current_user,
                include_internal_history=include_internal_history,
                market_feed=self.runtime_state.get("market_feed"),
            )
            if current_user and current_user.get("role") in {"admin", "super_admin"}:
                payload["live_pilot_control"] = deepcopy(self.live_pilot_control)
                payload["live_pilot_control"]["activation_phrase"] = LIVE_ACTIVATION_PHRASE
            return payload

    def sanitize_account(self, account: dict[str, Any]) -> dict[str, Any]:
        return self.account_directory.sanitize_account(account)

    def record_metric_snapshot(self) -> None:
        symbols = [self.portfolio_views.symbol_view(symbol, state) for symbol, state in self.symbol_states.items()]
        totals = self.portfolio_views.totals(symbols)
        self.metric_service.record(tick=self.tick_index, symbols=symbols, totals=totals)
