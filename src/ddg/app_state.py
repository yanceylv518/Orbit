from __future__ import annotations

import math
import re
import secrets
import threading
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from ddg.auth import hash_password, sanitize_user, verify_password
from ddg.binance import (
    BinanceConfigError,
    BinanceError,
    BinanceFuturesClient,
    account_can_connect,
    fingerprint,
    normalize_account_snapshot,
    normalize_positions,
    protect_credential,
)
from ddg.config import load_config
from ddg.engine import EventEngine, d, now_iso, q
from ddg.planning import generate_account_execution_plans
from ddg.reporting import DailyReportBuilder
from ddg.storage import make_state_store, mysql_status


INITIAL_PRICES = {
    "BTCUSDT": Decimal("60000"),
    "ETHUSDT": Decimal("3400"),
    "SOLUSDT": Decimal("145"),
}

EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")


class AppState:
    def __init__(self, config_path: str | None = None):
        self.root = Path(__file__).resolve().parents[2]
        self.config = load_config(config_path)
        self.lock = threading.RLock()
        self.mock_data_enabled = bool(self.config["runtime"].get("mock_data_enabled", False))
        self.running = bool(self.config["runtime"].get("auto_start", True)) and self.mock_data_enabled
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
        self.store = make_state_store(self.root, self.config["storage"], self.config)
        self.sessions: dict[str, str] = {}
        self._load_directory_from_store()
        self.strategy = self.config["strategy_instances"][0]
        self.account_run_configs = deepcopy(self.config.get("account_run_configs", []))
        self._ensure_account_run_configs()
        self.engine = EventEngine(self.strategy)
        self.report_builder = DailyReportBuilder(self.root)
        if not self._restore_runtime():
            self._initialize_runtime()
        self._ensure_account_run_configs()
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
        self.symbol_states = {}
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
            self.strategy_events.clear()
            self.trade_events.clear()
            self.risk_events.clear()
            self.admin_audit_logs.clear()
            self.daily_reports.clear()
            self.binance_account_snapshots.clear()
            self.execution_plans.clear()
            self.metric_history.clear()
            self.symbol_metric_history.clear()
            self.symbol_states.clear()
            self.price_history.clear()
            self._initialize_runtime()
            if self.mock_data_enabled:
                self.record_metric_snapshot()
            self.persist()
            return self.snapshot()

    def set_running(self, running: bool, actor: str = "admin_001") -> dict[str, Any]:
        with self.lock:
            before = {"running": self.running}
            self.running = running
            self.strategy["status"] = "running" if running else "paused"
            self.add_audit(
                actor=actor,
                action_type="START_STRATEGY" if running else "PAUSE_STRATEGY",
                reason="通过控制台切换运行状态。",
                before_value=before,
                after_value={"running": self.running, "strategy_status": self.strategy["status"]},
            )
            self.persist()
            return self.snapshot()

    def admin_emergency_stop(self, actor: str = "admin_001", reason: str | None = None) -> dict[str, Any]:
        with self.lock:
            before = self.control_state()
            self.running = False
            self.strategy["status"] = "emergency_stopped"
            for account in self.config["exchange_accounts"]:
                account["status"] = "paused_by_admin"
            self.add_audit(
                actor=actor,
                action_type="GLOBAL_EMERGENCY_STOP",
                reason=reason or "管理员触发全局急停，暂停系统策略并冻结全部交易账户。",
                before_value=before,
                after_value=self.control_state(),
            )
            self.persist()
            return self.snapshot()

    def admin_resume(self, actor: str = "admin_001", reason: str | None = None) -> dict[str, Any]:
        with self.lock:
            before = self.control_state()
            self.running = True
            self.strategy["status"] = "running"
            for account in self.config["exchange_accounts"]:
                if account.get("status") == "paused_by_admin":
                    account["status"] = "active"
            self.add_audit(
                actor=actor,
                action_type="RESUME_AFTER_EMERGENCY_STOP",
                reason=reason or "管理员恢复 dry_run 策略运行。",
                before_value=before,
                after_value=self.control_state(),
            )
            self.persist()
            return self.snapshot()

    def control_state(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "strategy_status": self.strategy.get("status", "running"),
            "account_statuses": {
                account["id"]: account.get("status", "active")
                for account in self.config["exchange_accounts"]
            },
        }

    def _ensure_account_run_configs(self) -> None:
        existing = {
            item.get("account_id"): item
            for item in self.account_run_configs
            if item.get("account_id")
        }
        next_configs: list[dict[str, Any]] = []
        for account in self.config.get("exchange_accounts", []):
            default = self.default_account_run_config(account)
            current = deepcopy(existing.get(account["id"], {}))
            merged = self.merge_run_config(default, current)
            merged["account_id"] = account["id"]
            merged["updated_at"] = current.get("updated_at", default["updated_at"])
            next_configs.append(merged)
        self.account_run_configs = next_configs
        self.config["account_run_configs"] = deepcopy(next_configs)

    def default_account_run_config(self, account: dict[str, Any]) -> dict[str, Any]:
        now = now_iso()
        symbols = list(self.strategy.get("symbols", []))
        budgets = {
            symbol: float(self.strategy.get("symbol_budget_usdt", {}).get(symbol, 0))
            for symbol in symbols
        }
        return {
            "id": f"run_{account['id']}",
            "account_id": account["id"],
            "strategy_id": self.strategy["id"],
            "enabled": True,
            "mode": "plan_only",
            "status": "active",
            "symbols": symbols,
            "symbol_budget_usdt": budgets,
            "base_position_usdt": float(self.strategy["strategy"].get("base_position_usdt", 0)),
            "max_single_order_usdt": 20.0,
            "allow_reduce_only": True,
            "allow_add_position": False,
            "allow_market_orders": False,
            "created_at": now,
            "updated_at": now,
        }

    def merge_run_config(self, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key in (
            "id",
            "strategy_id",
            "enabled",
            "mode",
            "status",
            "symbols",
            "symbol_budget_usdt",
            "base_position_usdt",
            "max_single_order_usdt",
            "allow_reduce_only",
            "allow_add_position",
            "allow_market_orders",
            "created_at",
            "updated_at",
        ):
            if key in incoming:
                merged[key] = incoming[key]
        merged["enabled"] = bool(merged.get("enabled", True))
        merged["mode"] = merged.get("mode") if merged.get("mode") in ("plan_only", "disabled") else "plan_only"
        merged["status"] = "active" if merged["enabled"] else "disabled"
        merged["symbols"] = [
            str(symbol).strip().upper()
            for symbol in merged.get("symbols", [])
            if str(symbol).strip()
        ]
        if not merged["symbols"]:
            merged["symbols"] = list(base.get("symbols", []))
        budgets = merged.get("symbol_budget_usdt") or {}
        merged["symbol_budget_usdt"] = {
            symbol: max(0.0, float(budgets.get(symbol, base.get("symbol_budget_usdt", {}).get(symbol, 0))))
            for symbol in merged["symbols"]
        }
        merged["base_position_usdt"] = max(0.0, float(merged.get("base_position_usdt", 0)))
        merged["max_single_order_usdt"] = max(0.0, float(merged.get("max_single_order_usdt", 0)))
        merged["allow_reduce_only"] = bool(merged.get("allow_reduce_only", True))
        merged["allow_add_position"] = bool(merged.get("allow_add_position", False))
        merged["allow_market_orders"] = False
        return merged

    def validate_external_id(self, value: str, label: str) -> str:
        value = str(value or "").strip()
        if not EXTERNAL_ID_RE.match(value):
            raise ValueError(f"{label} 只能包含字母、数字、下划线和短横线，长度 2-64 位。")
        return value

    def is_admin_user_id(self, user_id: str) -> bool:
        user = self.user_by_id(user_id)
        return bool(user and user.get("role") in ("admin", "super_admin"))

    def upsert_business_user(self, incoming: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.lock:
            if not self.is_admin_user_id(actor):
                return {"ok": False, "error": "只有管理员可以维护业务用户。"}
            try:
                user_id = self.validate_external_id(str(incoming.get("user_id", "")), "用户 ID")
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            name = str(incoming.get("name") or user_id).strip()
            email = str(incoming.get("email") or "").strip() or None
            status = str(incoming.get("status") or "active").strip()
            if status not in ("active", "disabled", "paused"):
                return {"ok": False, "error": "用户状态只能是 active、disabled 或 paused。"}

            existing = self.user_by_id(user_id)
            if existing and existing.get("role") in ("admin", "super_admin"):
                return {"ok": False, "error": "管理员账号不属于业务用户，不能在这里维护。"}

            before = deepcopy(existing or {})
            if existing:
                existing.update({
                    "name": name,
                    "email": email,
                    "role": "user",
                    "status": status,
                })
                user = existing
            else:
                user = {
                    "id": user_id,
                    "name": name,
                    "email": email,
                    "role": "user",
                    "status": status,
                }
                self.config["users"].append(user)

            self.add_audit(
                actor=actor,
                action_type="UPSERT_BUSINESS_USER",
                reason=f"维护业务用户：{user_id}",
                before_value=before,
                after_value=deepcopy(user),
            )
            self.persist()
            return {"ok": True, "user": sanitize_user(user)}

    def upsert_exchange_account(self, incoming: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.lock:
            if not self.is_admin_user_id(actor):
                return {"ok": False, "error": "只有管理员可以新增或编辑交易账户。"}
            try:
                account_id = self.validate_external_id(str(incoming.get("account_id", "")), "账户 ID")
                user_id = self.validate_external_id(str(incoming.get("user_id", "")), "所属用户 ID")
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}

            owner = self.user_by_id(user_id)
            if not owner or owner.get("role") in ("admin", "super_admin"):
                return {"ok": False, "error": "交易账户必须绑定到一个业务用户，不能绑定管理员。"}

            status = str(incoming.get("status") or "active").strip()
            if status not in ("active", "disabled", "paused_by_admin"):
                return {"ok": False, "error": "账户状态只能是 active、disabled 或 paused_by_admin。"}

            existing = self.account_by_id(account_id)
            before = deepcopy(existing or {})
            next_account = deepcopy(existing or {})
            next_account.update({
                "id": account_id,
                "user_id": user_id,
                "exchange": "binance",
                "market_type": "futures",
                "account_label": str(incoming.get("account_label") or account_id).strip(),
                "testnet": bool(incoming.get("testnet", True)),
                "dry_run": bool(incoming.get("dry_run", True)),
                "hedge_mode_required": bool(incoming.get("hedge_mode_required", True)),
                "status": status,
            })
            next_account["hedge_mode_enabled"] = bool(
                next_account.get("hedge_mode_enabled", next_account["hedge_mode_required"])
            )
            next_account.setdefault("permissions", {})

            if existing:
                existing.update(next_account)
                account = existing
            else:
                account = next_account
                self.config["exchange_accounts"].append(account)

            if before and (
                before.get("user_id") != account.get("user_id")
                or before.get("testnet") != account.get("testnet")
                or before.get("hedge_mode_required") != account.get("hedge_mode_required")
            ):
                self.binance_account_snapshots.pop(account_id, None)

            self._ensure_account_run_configs()
            self.add_audit(
                actor=actor,
                action_type="UPSERT_EXCHANGE_ACCOUNT",
                reason=f"维护 Binance 交易账户：{account_id}",
                before_value=before,
                after_value={
                    key: value
                    for key, value in account.items()
                    if key not in ("api_key_ref", "secret_ref")
                },
            )
            self.persist()
            return {"ok": True, "account": self.sanitize_account(account)}

    def account_run_config(self, account_id: str) -> dict[str, Any] | None:
        for item in self.account_run_configs:
            if item.get("account_id") == account_id:
                return item
        return None

    def update_account_run_config(self, account_id: str, incoming: dict[str, Any], actor: str) -> dict[str, Any]:
        with self.lock:
            account = self.account_by_id(account_id)
            if not account:
                return {"ok": False, "error": f"账户不存在：{account_id}"}
            actor_user = self.user_by_id(actor)
            actor_is_admin = bool(actor_user and actor_user.get("role") in ("admin", "super_admin"))
            if not actor_is_admin and account.get("user_id") != actor:
                return {"ok": False, "error": "账户运行配置只能由账户所属用户或管理员维护。"}
            self._ensure_account_run_configs()
            before = deepcopy(self.account_run_config(account_id))
            default = self.default_account_run_config(account)
            next_config = self.merge_run_config(default, {**(before or {}), **incoming})
            next_config["account_id"] = account_id
            next_config["updated_at"] = now_iso()
            replaced = False
            for index, item in enumerate(self.account_run_configs):
                if item.get("account_id") == account_id:
                    self.account_run_configs[index] = next_config
                    replaced = True
                    break
            if not replaced:
                self.account_run_configs.append(next_config)
            self.config["account_run_configs"] = deepcopy(self.account_run_configs)
            new_plans = self._build_execution_plans_for_accounts({account_id})
            self.add_audit(
                actor=actor,
                action_type="UPDATE_ACCOUNT_RUN_CONFIG",
                reason=f"更新账户运行配置：{account_id}",
                before_value=before or {},
                after_value=deepcopy(next_config),
            )
            self.persist()
            return {
                "ok": True,
                "account_id": account_id,
                "run_config": deepcopy(next_config),
                "plans": deepcopy(new_plans),
            }

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
        user_id = self.config.get("auth", {}).get("default_operator_user_id", "admin_001")
        user = self.user_by_id(user_id)
        if user and user.get("status", "active") == "active":
            return user
        for candidate in self.config.get("users", []):
            if candidate.get("role") in ("admin", "super_admin") and candidate.get("status", "active") == "active":
                return candidate
        return None

    def auth_user(self, login: str) -> dict[str, Any] | None:
        auth_lookup = getattr(self.store, "auth_user", None)
        if callable(auth_lookup):
            user = auth_lookup(login)
            if user:
                return user
        for user in self.config.get("users", []):
            if login in (user.get("id"), user.get("email")):
                return dict(user)
        return None

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        for user in self.config.get("users", []):
            if user.get("id") == user_id:
                return user
        return None

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
        with self.lock:
            before = deepcopy(self.strategy["strategy"]["events"])
            self.strategy["strategy"]["events"] = self.merge_known_config(before, incoming)
            self.engine = EventEngine(self.strategy)
            self.add_audit(
                actor=actor,
                action_type="UPDATE_EVENT_CONFIG",
                reason="管理员更新三大策略事件参数。",
                before_value=before,
                after_value=deepcopy(self.strategy["strategy"]["events"]),
            )
            self.persist()
            return self.snapshot()

    def merge_known_config(self, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        for key, current_value in current.items():
            if key not in incoming:
                continue
            incoming_value = incoming[key]
            if isinstance(current_value, dict) and isinstance(incoming_value, dict):
                merged[key] = self.merge_known_config(current_value, incoming_value)
            elif isinstance(current_value, bool):
                merged[key] = bool(incoming_value)
            elif isinstance(current_value, int) and not isinstance(current_value, bool):
                merged[key] = max(0, int(float(incoming_value)))
            elif isinstance(current_value, float):
                merged[key] = max(0.0, float(incoming_value))
            else:
                merged[key] = incoming_value
        return merged

    def add_audit(
        self,
        actor: str,
        action_type: str,
        reason: str,
        before_value: dict[str, Any] | None = None,
        after_value: dict[str, Any] | None = None,
    ) -> None:
        self.admin_audit_logs.insert(0, {
            "id": f"audit_{int(time.time() * 1000)}",
            "timestamp": now_iso(),
            "admin_user_id": actor,
            "action_type": action_type,
            "target_strategy_id": self.strategy["id"],
            "before_value": before_value or {},
            "after_value": after_value or {},
            "reason": reason,
        })

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
                for event in events:
                    event["user_id"] = None
                    event["exchange_account_id"] = None
                    event["strategy_instance_id"] = self.strategy["id"]
                    self.strategy_events.insert(0, event)
                    for trade in event["trades"]:
                        trade["strategy_event_id"] = event["id"]
                        trade["user_id"] = None
                        trade["exchange_account_id"] = None
                        trade["strategy_instance_id"] = self.strategy["id"]
                        self.trade_events.insert(0, trade)
                for risk in risks:
                    risk["user_id"] = None
                    risk["exchange_account_id"] = None
                    risk["strategy_instance_id"] = self.strategy["id"]
                    self.risk_events.insert(0, risk)
            self.strategy_events = self.strategy_events[:300]
            self.trade_events = self.trade_events[:600]
            self.risk_events = self.risk_events[:200]
            self.record_metric_snapshot()
            persist_payload = self.persist_payload()
            snapshot = self.snapshot()
        self.store.save(persist_payload)
        return snapshot

    def generate_daily_report(self, actor: str = "admin_001") -> dict[str, Any]:
        with self.lock:
            report = self.report_builder.generate(self.snapshot(include_internal_history=True))
            self.daily_reports.insert(0, report)
            self.daily_reports = self.daily_reports[:30]
            self.add_audit(
                actor=actor,
                action_type="GENERATE_DAILY_REPORT",
                reason=f"生成 {report['date']} 日报。",
                after_value={"markdown_path": report["markdown_path"]},
            )
            self.persist()
            snapshot = self.snapshot()
            snapshot["generated_report"] = report
            return snapshot

    def sync_binance_account(self, account_id: str, actor: str = "system") -> dict[str, Any]:
        account = self.account_by_id(account_id)
        if not account:
            return {"ok": False, "error": f"账户不存在：{account_id}"}
        actor_user = self.user_by_id(actor) if actor != "system" else None
        actor_is_admin = bool(actor_user and actor_user.get("role") in ("admin", "super_admin"))
        if actor != "system" and not actor_is_admin and account.get("user_id") != actor:
            return {
                "ok": False,
                "status": "forbidden",
                "error": "Binance 同步只能由账户所属用户或管理员执行。",
            }

        connection = account_can_connect(account)
        snapshot: dict[str, Any] = {
            "ok": False,
            "account_id": account_id,
            "account_label": account.get("account_label", account_id),
            "testnet": bool(account.get("testnet", True)),
            "dry_run": bool(account.get("dry_run", True)),
            "api_key_present": connection["api_key_present"],
            "secret_present": connection["secret_present"],
            "api_key_fingerprint": connection["api_key_fingerprint"] or account.get("api_key_fingerprint"),
            "synced_at": now_iso(),
        }

        if not connection["api_key_present"] or not connection["secret_present"]:
            snapshot["status"] = "missing_credentials"
            snapshot["error"] = "缺少 Binance API Key 或 Secret。请在账户页配置。"
        else:
            try:
                client = BinanceFuturesClient.from_account(account)
                account_payload = client.account_information()
                positions_payload = client.position_risk()
                position_mode = client.position_mode()
                snapshot.update(normalize_account_snapshot(account, account_payload))
                snapshot["synced_at"] = now_iso()
                snapshot["ok"] = True
                snapshot["status"] = "synced"
                snapshot["position_mode"] = {
                    "dual_side_position": bool(position_mode.get("dualSidePosition")),
                    "hedge_mode_required": bool(account.get("hedge_mode_required", account.get("hedge_mode_enabled", False))),
                }
                snapshot["position_mode"]["hedge_mode_ok"] = (
                    not snapshot["position_mode"]["hedge_mode_required"]
                    or snapshot["position_mode"]["dual_side_position"]
                )
                symbols = self.strategy.get("symbols", []) if self.mock_data_enabled else None
                snapshot["positions"] = normalize_positions(positions_payload, symbols)
            except (BinanceConfigError, BinanceError) as exc:
                snapshot["status"] = "error"
                snapshot["error"] = str(exc)

        with self.lock:
            self.binance_account_snapshots[account_id] = snapshot
            if snapshot.get("api_key_fingerprint"):
                account["api_key_fingerprint"] = snapshot["api_key_fingerprint"]
            if snapshot.get("position_mode"):
                account["hedge_mode_enabled"] = bool(snapshot["position_mode"]["dual_side_position"])
            new_plans = self._build_execution_plans_for_accounts({account_id})
            self.add_audit(
                actor=actor,
                action_type="SYNC_BINANCE_ACCOUNT",
                reason=f"同步 Binance 账户 {account_id} 只读数据。",
                after_value={
                    "account_id": account_id,
                    "status": snapshot.get("status"),
                    "hedge_mode_ok": snapshot.get("position_mode", {}).get("hedge_mode_ok"),
                    "execution_plan_count": len(new_plans),
                },
            )
            self.persist()
            return snapshot

    def update_binance_credentials(
        self,
        account_id: str,
        actor: str,
        api_key: str,
        api_secret: str,
    ) -> dict[str, Any]:
        api_key = api_key.strip()
        api_secret = api_secret.strip()
        if not api_key or not api_secret:
            return {"ok": False, "error": "请填写 Binance API Key 和 Secret。"}

        with self.lock:
            account = self.account_by_id(account_id)
            if not account:
                return {"ok": False, "error": f"账户不存在：{account_id}"}
            actor_user = self.user_by_id(actor)
            actor_is_admin = bool(actor_user and actor_user.get("role") in ("admin", "super_admin"))
            if not actor_is_admin and account.get("user_id") != actor:
                return {"ok": False, "error": "API Key/Secret 只能由账户所属用户或管理员维护。"}

            account["api_key_ref"] = protect_credential(api_key)
            account["secret_ref"] = protect_credential(api_secret)
            account["api_key_fingerprint"] = fingerprint(api_key)
            self.binance_account_snapshots.pop(account_id, None)

            setter = getattr(self.store, "set_account_credentials", None)
            if callable(setter):
                setter(
                    account_id,
                    account["user_id"],
                    account["api_key_ref"],
                    account["api_key_fingerprint"],
                    account["secret_ref"],
                )
            self.add_audit(
                actor=actor,
                action_type="SET_BINANCE_CREDENTIALS",
                reason=f"更新 Binance API 凭证：{account_id}",
                after_value={
                    "account_id": account_id,
                    "api_key_fingerprint": account["api_key_fingerprint"],
                },
            )
            self.persist()
            return {
                "ok": True,
                "account_id": account_id,
                "api_key_fingerprint": account["api_key_fingerprint"],
            }

    def account_by_id(self, account_id: str) -> dict[str, Any] | None:
        for account in self.config.get("exchange_accounts", []):
            if account.get("id") == account_id:
                return account
        return None

    def generate_execution_plans(self, account_id: str | None = None, actor: str = "system") -> dict[str, Any]:
        with self.lock:
            if account_id and not self.account_by_id(account_id):
                return {"ok": False, "error": f"账户不存在：{account_id}"}
            account_ids = {account_id} if account_id else {account["id"] for account in self.config.get("exchange_accounts", [])}
            plans = self._build_execution_plans_for_accounts(account_ids)
            self.add_audit(
                actor=actor,
                action_type="GENERATE_EXECUTION_PLANS",
                reason="生成第一阶段执行计划，仅用于实盘前演练，不会下单。",
                after_value={
                    "account_ids": sorted(account_ids),
                    "plan_count": len(plans),
                },
            )
            self.persist()
            return {"ok": True, "plans": deepcopy(plans)}

    def _build_execution_plans_for_accounts(self, account_ids: set[str]) -> list[dict[str, Any]]:
        self._ensure_account_run_configs()
        accounts = [
            account for account in self.config.get("exchange_accounts", [])
            if account["id"] in account_ids
        ]
        new_plans: list[dict[str, Any]] = []
        for account in accounts:
            run_config = self.account_run_config(account["id"])
            if not run_config:
                continue
            snapshot = self.binance_account_snapshots.get(account["id"])
            new_plans.extend(generate_account_execution_plans(account, run_config, self.strategy, snapshot))
        self.execution_plans = [
            plan for plan in self.execution_plans
            if plan.get("account_id") not in account_ids
        ]
        self.execution_plans = (new_plans + self.execution_plans)[:300]
        return new_plans

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
        while True:
            if self.running and self.mock_data_enabled:
                self.tick_once()
            time.sleep(interval)

    def start_background(self) -> None:
        thread = threading.Thread(target=self.background_loop, name="ddg-runner", daemon=True)
        thread.start()

    def persist(self) -> None:
        self.store.save(self.persist_payload())

    def persist_payload(self) -> dict[str, Any]:
        symbol_views = {}
        for symbol, state in self.symbol_states.items():
            symbol_views[symbol] = self.symbol_view(symbol, state)
        return {
            "tick_index": self.tick_index,
            "running": self.running,
            "users": deepcopy(self.config["users"]),
            "exchange_accounts": deepcopy(self.config["exchange_accounts"]),
            "account_run_configs": deepcopy(self.account_run_configs),
            "strategy_instance": deepcopy(self.strategy),
            "symbol_states": deepcopy(self.symbol_states),
            "symbol_views": symbol_views,
            "strategy_events": deepcopy(self.strategy_events),
            "trade_events": deepcopy(self.trade_events),
            "risk_events": deepcopy(self.risk_events),
            "admin_audit_logs": deepcopy(self.admin_audit_logs),
            "daily_reports": deepcopy(self.daily_reports),
            "binance_account_snapshots": deepcopy(self.binance_account_snapshots),
            "execution_plans": deepcopy(self.execution_plans),
            "price_history": deepcopy(self.price_history),
            "metric_history": deepcopy(self.metric_history),
            "symbol_metric_history": deepcopy(self.symbol_metric_history),
            "updated_at": now_iso(),
        }

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "server_time": now_iso(),
            "auth": {
                "authenticated": False,
                "login_required": self.login_required(),
            },
        }

    def snapshot(
        self,
        current_user: dict[str, Any] | None = None,
        include_internal_history: bool = False,
    ) -> dict[str, Any]:
        with self.lock:
            symbols = self.runtime_symbols()
            totals = self.totals(symbols)
            trade_events = self.trade_events[:120] if include_internal_history else []
            metric_history = self.metric_history if include_internal_history else []
            symbol_metric_history = self.symbol_metric_history if include_internal_history else {}
            payload = {
                "server_time": now_iso(),
                "running": self.running,
                "tick_index": self.tick_index,
                "users": self.config["users"],
                "exchange_accounts": [self.sanitize_account(account) for account in self.config["exchange_accounts"]],
                "account_run_configs": deepcopy(self.account_run_configs),
                "strategy": self.strategy_summary(symbols, totals),
                "admin_overview": self.admin_overview(symbols, totals),
                "symbols": symbols,
                "strategy_events": deepcopy(self.strategy_events[:80]),
                "trade_events": deepcopy(trade_events),
                "risk_events": deepcopy(self.risk_events[:60]),
                "admin_audit_logs": deepcopy(self.admin_audit_logs[:60]),
                "daily_reports": deepcopy(self.daily_reports[:30]),
                "binance_account_snapshots": deepcopy(self.binance_account_snapshots),
                "execution_plans": deepcopy(self.execution_plans[:120]),
                "price_history": deepcopy(self.price_history),
                "metric_history": deepcopy(metric_history),
                "symbol_metric_history": deepcopy(symbol_metric_history),
                "event_config": self.strategy["strategy"]["events"],
                "storage": {
                    "driver": self.config["storage"].get("driver", "json"),
                    "json_path": self.config["storage"].get("json_path", "data/runtime_state.json"),
                    "mysql": mysql_status(),
                },
            }
            if current_user:
                payload = self.apply_permissions(payload, current_user)
                payload["auth"] = {
                    "authenticated": True,
                    "login_required": self.login_required(),
                    "current_user": sanitize_user(current_user),
                    "permissions": self.user_permissions(current_user),
                }
            return payload

    def sanitize_account(self, account: dict[str, Any]) -> dict[str, Any]:
        connection = account_can_connect(account)
        return {
            "id": account["id"],
            "user_id": account["user_id"],
            "exchange": account.get("exchange", "binance"),
            "market_type": account.get("market_type", "futures"),
            "account_label": account.get("account_label", account["id"]),
            "testnet": bool(account.get("testnet", True)),
            "dry_run": bool(account.get("dry_run", True)),
            "hedge_mode_required": bool(account.get("hedge_mode_required", account.get("hedge_mode_enabled", False))),
            "hedge_mode_enabled": bool(account.get("hedge_mode_enabled", account.get("hedge_mode_required", False))),
            "api_key_configured": bool(account.get("api_key_ref")),
            "secret_configured": bool(account.get("secret_ref")),
            "api_key_present": connection["api_key_present"],
            "secret_present": connection["secret_present"],
            "api_key_fingerprint": connection["api_key_fingerprint"] or account.get("api_key_fingerprint"),
            "credential_error": connection.get("credential_error"),
            "status": account.get("status", "active"),
        }

    def apply_permissions(self, payload: dict[str, Any], current_user: dict[str, Any]) -> dict[str, Any]:
        if current_user.get("role") in ("admin", "super_admin"):
            return payload

        user_id = current_user["id"]
        visible_accounts = [
            account for account in payload["exchange_accounts"]
            if account.get("user_id") == user_id
        ]
        account_ids = {account["id"] for account in visible_accounts}
        filtered = deepcopy(payload)
        filtered["users"] = [user for user in payload["users"] if user.get("id") == user_id]
        filtered["exchange_accounts"] = visible_accounts
        filtered["account_run_configs"] = [
            item for item in payload.get("account_run_configs", [])
            if item.get("account_id") in account_ids
        ]
        filtered["binance_account_snapshots"] = {
            account_id: snapshot
            for account_id, snapshot in payload.get("binance_account_snapshots", {}).items()
            if account_id in account_ids
        }
        filtered["admin_overview"] = {
            "users": [
                user for user in payload["admin_overview"]["users"]
                if user.get("user_id") == user_id
            ],
            "accounts": [
                account for account in payload["admin_overview"]["accounts"]
                if account.get("user_id") == user_id
            ],
            "permissions": {
                "can_view_all_accounts": False,
                "can_emergency_stop": False,
                "can_resume_dry_run": False,
                "can_view_secret": False,
            },
        }
        filtered["strategy_events"] = [
            event for event in payload["strategy_events"]
            if event.get("user_id") == user_id
        ]
        filtered["trade_events"] = [
            event for event in payload["trade_events"]
            if event.get("user_id") == user_id
        ]
        filtered["risk_events"] = [
            event for event in payload["risk_events"]
            if event.get("user_id") in (user_id, None)
        ]
        filtered["execution_plans"] = [
            plan for plan in payload.get("execution_plans", [])
            if plan.get("account_id") in account_ids
        ]
        if not self.mock_data_enabled:
            filtered["symbols"] = self.real_symbol_views(account_ids)
            filtered["strategy"] = self.strategy_summary(
                filtered["symbols"],
                self.totals(filtered["symbols"]),
                account_ids,
            )
        elif self.mock_data_enabled:
            filtered["symbols"] = []
            filtered["price_history"] = {}
            filtered["symbol_metric_history"] = {}
            filtered["strategy"] = {
                "id": None,
                "name": "未绑定策略",
                "version": "-",
                "mode": "-",
                "status": "unassigned",
                "symbol_count": 0,
                "symbols": [],
                "today_pnl": 0,
                "today_pnl_pct": 0,
                "total_equity": 0,
                "risk_status": "normal",
            }
        return filtered

    def user_permissions(self, user: dict[str, Any]) -> dict[str, bool]:
        is_admin = user.get("role") in ("admin", "super_admin")
        return {
            "can_view_all_accounts": is_admin,
            "can_manage_users": is_admin,
            "can_emergency_stop": is_admin,
            "can_update_strategy": is_admin,
            "can_generate_report": is_admin,
            "can_update_account_run_config": True,
            "can_generate_execution_plan": True,
            "can_view_secret": False,
        }

    def runtime_symbols(self, account_ids: set[str] | None = None) -> list[dict[str, Any]]:
        if self.mock_data_enabled:
            return [
                self.symbol_view(symbol, state)
                for symbol, state in self.symbol_states.items()
            ]
        return self.real_symbol_views(account_ids)

    def real_symbol_views(self, account_ids: set[str] | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        account_by_id = {
            account["id"]: account
            for account in self.config.get("exchange_accounts", [])
        }
        for account_id, snapshot in self.binance_account_snapshots.items():
            if account_ids is not None and account_id not in account_ids:
                continue
            if snapshot.get("status") != "synced" and not snapshot.get("ok"):
                continue
            positions = snapshot.get("positions") or []
            for position in positions:
                symbol = position.get("symbol")
                if not symbol:
                    continue
                qty = float(position.get("position_amt") or 0)
                notional = float(position.get("notional") or 0)
                mark_price = float(position.get("mark_price") or 0)
                entry_price = float(position.get("entry_price") or 0)
                pnl = float(position.get("unrealized_profit") or 0)
                side = str(position.get("position_side") or "BOTH").upper()
                is_short = side == "SHORT" or qty < 0
                long_qty = abs(qty) if not is_short else 0
                short_qty = abs(qty) if is_short else 0
                account = account_by_id.get(account_id, {})
                rows.append({
                    "symbol": symbol,
                    "account_id": account_id,
                    "account_label": account.get("account_label", account_id),
                    "state": "REAL_POSITION",
                    "price": mark_price or entry_price,
                    "base_price": entry_price or mark_price,
                    "move_pct": ((mark_price / entry_price) - 1) * 100 if mark_price and entry_price else 0,
                    "high_since_base": mark_price or entry_price,
                    "low_since_base": mark_price or entry_price,
                    "long_qty": long_qty,
                    "short_qty": short_qty,
                    "base_qty": 0,
                    "long_entry_price": entry_price if long_qty else 0,
                    "short_entry_price": entry_price if short_qty else 0,
                    "long_unrealized_pnl": pnl if long_qty else 0,
                    "short_unrealized_pnl": pnl if short_qty else 0,
                    "unrealized_pnl": pnl,
                    "realized_pnl": 0,
                    "fee_total": 0,
                    "slippage_total": 0,
                    "funding_total": 0,
                    "net_exposure": notional,
                    "gross_exposure": abs(notional),
                    "equity": pnl,
                    "budget_usdt": 0,
                    "profit_transfer_count": 0,
                    "loss_side_reduce_count": 0,
                    "recovery_count": 0,
                    "source": "binance",
                })
        return sorted(rows, key=lambda item: (item["account_label"], item["symbol"], item["short_qty"] > 0))

    def real_account_totals(self, account_id: str) -> dict[str, float | bool]:
        snapshot = self.binance_account_snapshots.get(account_id) or {}
        if snapshot.get("status") != "synced" and not snapshot.get("ok"):
            return {
                "has_real_data": False,
                "total_equity": 0.0,
                "today_pnl": 0.0,
                "today_pnl_pct": 0.0,
                "total_budget": 0.0,
            }
        total_equity = float(snapshot.get("total_margin_balance") or snapshot.get("total_wallet_balance") or 0)
        today_pnl = float(snapshot.get("total_unrealized_profit") or 0)
        basis = total_equity - today_pnl
        return {
            "has_real_data": True,
            "total_equity": total_equity,
            "today_pnl": today_pnl,
            "today_pnl_pct": (today_pnl / basis * 100) if basis else 0.0,
            "total_budget": basis,
        }

    def real_portfolio_totals(self, account_ids: set[str] | None = None) -> dict[str, float]:
        totals = {
            "total_budget": 0.0,
            "total_equity": 0.0,
            "today_pnl": 0.0,
            "today_pnl_pct": 0.0,
            "total_unrealized": 0.0,
            "total_realized": 0.0,
            "total_fees": 0.0,
            "total_slippage": 0.0,
            "max_drawdown": 0.0,
        }
        for account in self.config.get("exchange_accounts", []):
            account_id = account["id"]
            if account_ids is not None and account_id not in account_ids:
                continue
            account_totals = self.real_account_totals(account_id)
            if not account_totals["has_real_data"]:
                continue
            totals["total_budget"] += float(account_totals["total_budget"])
            totals["total_equity"] += float(account_totals["total_equity"])
            totals["today_pnl"] += float(account_totals["today_pnl"])
            totals["total_unrealized"] += float(account_totals["today_pnl"])
        totals["today_pnl_pct"] = (
            totals["today_pnl"] / totals["total_budget"] * 100
            if totals["total_budget"]
            else 0.0
        )
        return totals

    def symbol_view(self, symbol: str, state: dict[str, Any]) -> dict[str, Any]:
        price = d(state["last_price"])
        base = d(state["base_price"])
        return {
            "symbol": symbol,
            "state": state["state"],
            "price": float(price),
            "base_price": float(base),
            "move_pct": float((price / base - Decimal("1")) * Decimal("100")),
            "high_since_base": float(d(state["high_since_base"])),
            "low_since_base": float(d(state["low_since_base"])),
            "long_qty": float(d(state["long_qty"])),
            "short_qty": float(d(state["short_qty"])),
            "base_qty": float(d(state["base_qty"])),
            "long_entry_price": float(d(state["long_entry_price"])),
            "short_entry_price": float(d(state["short_entry_price"])),
            "long_unrealized_pnl": float(d(state["long_unrealized_pnl"])),
            "short_unrealized_pnl": float(d(state["short_unrealized_pnl"])),
            "unrealized_pnl": float(d(state["long_unrealized_pnl"]) + d(state["short_unrealized_pnl"])),
            "realized_pnl": float(d(state["realized_pnl"])),
            "fee_total": float(d(state["fee_total"])),
            "slippage_total": float(d(state["slippage_total"])),
            "funding_total": float(d(state["funding_total"])),
            "net_exposure": float(d(state.get("net_exposure", "0"))),
            "gross_exposure": float(d(state.get("gross_exposure", "0"))),
            "equity": float(d(state.get("equity", state["budget_usdt"]))),
            "budget_usdt": float(d(state["budget_usdt"])),
            "profit_transfer_count": int(state.get("profit_transfer_count_in_trend", 0)),
            "loss_side_reduce_count": int(state.get("loss_side_reduce_count_in_trend", 0)),
            "recovery_count": int(state.get("recovery_count_in_trend", 0)),
        }

    def totals(self, symbols: list[dict[str, Any]]) -> dict[str, float]:
        total_budget = sum(s["budget_usdt"] for s in symbols)
        total_equity = sum(s["equity"] for s in symbols)
        total_unrealized = sum(s["unrealized_pnl"] for s in symbols)
        total_realized = sum(s["realized_pnl"] for s in symbols)
        return {
            "total_budget": total_budget,
            "total_equity": total_equity,
            "today_pnl": total_equity - total_budget,
            "today_pnl_pct": ((total_equity / total_budget) - 1) * 100 if total_budget else 0,
            "total_unrealized": total_unrealized,
            "total_realized": total_realized,
            "total_fees": sum(s["fee_total"] for s in symbols),
            "total_slippage": sum(s["slippage_total"] for s in symbols),
            "max_drawdown": min(0, min((s["equity"] - s["budget_usdt"] for s in symbols), default=0)),
        }

    def strategy_summary(
        self,
        symbols: list[dict[str, Any]],
        totals: dict[str, float],
        account_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        display_totals = totals if self.mock_data_enabled else self.real_portfolio_totals(account_ids)
        status = self.strategy.get("status", "running" if self.running else "paused")
        if self.running and status in ("paused", "emergency_stopped"):
            status = "running"
        if not self.running and status == "running":
            status = "paused"
        if not self.mock_data_enabled:
            status = "read_only"
        return {
            "id": self.strategy["id"],
            "scope": "system",
            "name": self.strategy["strategy_name"],
            "version": self.strategy["strategy_version"],
            "mode": "read_only" if not self.mock_data_enabled else self.strategy["mode"],
            "status": status,
            "symbol_count": len(symbols),
            "symbols": [s["symbol"] for s in symbols],
            "today_pnl": display_totals["today_pnl"],
            "today_pnl_pct": display_totals["today_pnl_pct"],
            "total_equity": display_totals["total_equity"],
            "risk_status": "normal" if not self.risk_events else "watch",
        }

    def admin_overview(self, symbols: list[dict[str, Any]], totals: dict[str, float]) -> dict[str, Any]:
        business_users = [
            user for user in self.config["users"]
            if user.get("role") not in ("admin", "super_admin")
        ]
        user_by_id = {user["id"]: user for user in business_users}
        account_rows = []
        user_rows = []

        for account in self.config["exchange_accounts"]:
            user = user_by_id.get(account["user_id"])
            if not user:
                continue
            account_totals = self.real_account_totals(account["id"])
            account_risks = [
                risk for risk in self.risk_events
                if risk.get("exchange_account_id") == account["id"]
            ]
            account_events = [
                event for event in self.strategy_events
                if event.get("exchange_account_id") == account["id"]
            ]
            account_rows.append({
                "user_id": user["id"],
                "user_name": user.get("name", user["id"]),
                "account_id": account["id"],
                "account_label": account.get("account_label", account["id"]),
                "exchange": account.get("exchange", "-"),
                "market_type": account.get("market_type", "-"),
                "testnet": bool(account.get("testnet", False)),
                "dry_run": bool(account.get("dry_run", False)),
                "hedge_mode_required": bool(account.get("hedge_mode_required", account.get("hedge_mode_enabled", False))),
                "account_status": account.get("status", "active"),
                "symbols": sorted({
                    symbol["symbol"]
                    for symbol in symbols
                    if symbol.get("account_id") == account["id"]
                }),
                "total_budget": float(account_totals["total_budget"]),
                "total_equity": float(account_totals["total_equity"]),
                "today_pnl": float(account_totals["today_pnl"]),
                "risk_status": "watch" if account_risks else "normal",
                "last_event_at": account_events[0]["timestamp"] if account_events else None,
                "last_risk_at": account_risks[0]["timestamp"] if account_risks else None,
            })

        for user in business_users:
            accounts = [item for item in account_rows if item["user_id"] == user["id"]]
            real_user_totals = {
                "total_equity": sum(float(account["total_equity"]) for account in accounts),
                "today_pnl": sum(float(account["today_pnl"]) for account in accounts),
            }
            user_rows.append({
                "user_id": user["id"],
                "user_name": user.get("name", user["id"]),
                "email": user.get("email"),
                "role": user.get("role", "user"),
                "status": user.get("status", "active"),
                "account_count": len(accounts),
                "total_equity": real_user_totals["total_equity"],
                "today_pnl": real_user_totals["today_pnl"],
                "risk_status": "watch" if any(account["risk_status"] == "watch" for account in accounts) else "normal",
            })

        return {
            "users": user_rows,
            "accounts": account_rows,
            "permissions": {
                "can_view_all_accounts": True,
                "can_emergency_stop": True,
                "can_resume_dry_run": True,
                "can_view_secret": False,
            },
        }

    def record_metric_snapshot(self) -> None:
        symbols = [self.symbol_view(symbol, state) for symbol, state in self.symbol_states.items()]
        totals = self.totals(symbols)
        timestamp = now_iso()
        self.metric_history.append({
            "tick": self.tick_index,
            "timestamp": timestamp,
            "total_equity": totals["total_equity"],
            "total_fee": totals["total_fees"],
            "total_slippage": totals["total_slippage"],
            "profit_transfer_count": sum(item["profit_transfer_count"] for item in symbols),
            "loss_side_reduce_count": sum(item["loss_side_reduce_count"] for item in symbols),
            "position_recovery_count": sum(item["recovery_count"] for item in symbols),
        })
        self.metric_history = self.metric_history[-500:]
        for symbol in symbols:
            history = self.symbol_metric_history.setdefault(symbol["symbol"], [])
            history.append({
                "tick": self.tick_index,
                "timestamp": timestamp,
                "equity": symbol["equity"],
                "long_notional": symbol["long_qty"] * symbol["price"],
                "short_notional": symbol["short_qty"] * symbol["price"],
                "net_exposure": symbol["net_exposure"],
                "gross_exposure": symbol["gross_exposure"],
                "fee_total": symbol["fee_total"],
            })
            self.symbol_metric_history[symbol["symbol"]] = history[-500:]
