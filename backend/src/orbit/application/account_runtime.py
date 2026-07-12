from __future__ import annotations

from copy import deepcopy
from typing import Any

from orbit.application.permissions import PermissionPolicy
from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.domain.strategy.engine import now_iso


class AccountRunConfigService:
    def __init__(
        self,
        permissions: PermissionPolicy,
        accounts: AccountRepository,
        configs: RunConfigRepository,
        strategy: dict[str, Any],
    ):
        self.permissions = permissions
        self.accounts = accounts
        self.configs = configs
        self.strategy = strategy

    def ensure_all(self) -> None:
        existing = {
            item.get("account_id"): item
            for item in self.configs.all()
            if item.get("account_id")
        }
        next_configs: list[dict[str, Any]] = []
        for account in self.accounts.accounts():
            default = self.default_for(account)
            current = deepcopy(existing.get(account["id"], {}))
            merged = self.merge(default, current)
            merged["account_id"] = account["id"]
            merged["updated_at"] = current.get("updated_at", default["updated_at"])
            next_configs.append(merged)
        self.configs.replace_all(next_configs)

    def update(
        self,
        account_id: str,
        incoming: dict[str, Any],
        *,
        actor: str,
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        account = self.accounts.account_by_id(account_id)
        if not account:
            return {"ok": False, "error": f"账户不存在：{account_id}"}
        if not self.permissions.can_access_account(actor_user, account):
            return {"ok": False, "error": "账户运行配置只能由账户所属用户或管理员维护。"}

        self.ensure_all()
        before = deepcopy(self.configs.get(account_id) or {})
        next_config = self.merge(self.default_for(account), {**before, **incoming})
        next_config["account_id"] = account_id
        next_config["updated_at"] = now_iso()
        saved = self.configs.save(next_config)
        return {
            "ok": True,
            "account_id": account_id,
            "run_config": deepcopy(saved),
            "_audit": {
                "actor": actor,
                "action_type": "UPDATE_ACCOUNT_RUN_CONFIG",
                "reason": f"更新账户运行配置：{account_id}",
                "before_value": before,
                "after_value": deepcopy(saved),
            },
        }

    def default_for(self, account: dict[str, Any]) -> dict[str, Any]:
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

    def merge(self, base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key in (
            "id", "strategy_id", "enabled", "mode", "status", "symbols",
            "symbol_budget_usdt", "base_position_usdt", "max_single_order_usdt",
            "allow_reduce_only", "allow_add_position", "allow_market_orders",
            "created_at", "updated_at",
        ):
            if key in incoming:
                merged[key] = incoming[key]
        merged["enabled"] = bool(merged.get("enabled", True))
        merged["mode"] = merged.get("mode") if merged.get("mode") in ("plan_only", "paper", "live", "disabled") else "plan_only"
        merged["status"] = "active" if merged["enabled"] else "disabled"
        merged["symbols"] = [
            str(symbol).strip().upper()
            for symbol in merged.get("symbols", [])
            if str(symbol).strip()
        ] or list(base.get("symbols", []))
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
