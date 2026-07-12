from __future__ import annotations

from copy import deepcopy
from typing import Any

from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.strategy_runtime_repository import StrategyRuntimeRepository


class StrategyControlService:
    def __init__(self, runtime: StrategyRuntimeRepository, accounts: AccountRepository):
        self.runtime = runtime
        self.accounts = accounts

    def state(self) -> dict[str, Any]:
        strategy = self.runtime.strategy()
        return {
            "running": self.runtime.is_running(),
            "strategy_status": strategy.get("status", "running"),
            "account_statuses": {
                account["id"]: account.get("status", "active")
                for account in self.accounts.accounts()
            },
        }

    def set_running(self, running: bool, *, actor: str) -> dict[str, Any]:
        before = self.state()
        self.runtime.set_running(running)
        self.runtime.strategy()["status"] = "running" if running else "paused"
        after = self.state()
        return {
            "ok": True,
            "state": after,
            "_audit": {
                "actor": actor,
                "action_type": "START_STRATEGY" if running else "PAUSE_STRATEGY",
                "reason": "通过控制台切换运行状态。",
                "before_value": before,
                "after_value": after,
            },
        }

    def emergency_stop(self, *, actor: str, reason: str | None = None) -> dict[str, Any]:
        before = deepcopy(self.state())
        self.runtime.set_running(False)
        self.runtime.strategy()["status"] = "emergency_stopped"
        for account in self.accounts.accounts():
            account["status"] = "paused_by_admin"
            self.accounts.save_account(account)
        after = self.state()
        return {
            "ok": True,
            "state": after,
            "_audit": {
                "actor": actor,
                "action_type": "GLOBAL_EMERGENCY_STOP",
                "reason": reason or "管理员触发全局急停，暂停系统策略并冻结全部交易账户。",
                "before_value": before,
                "after_value": after,
            },
        }

    def resume(self, *, actor: str, reason: str | None = None) -> dict[str, Any]:
        before = deepcopy(self.state())
        self.runtime.set_running(True)
        self.runtime.strategy()["status"] = "running"
        for account in self.accounts.accounts():
            if account.get("status") == "paused_by_admin":
                account["status"] = "active"
                self.accounts.save_account(account)
        after = self.state()
        return {
            "ok": True,
            "state": after,
            "_audit": {
                "actor": actor,
                "action_type": "RESUME_AFTER_EMERGENCY_STOP",
                "reason": reason or "管理员恢复 dry_run 策略运行。",
                "before_value": before,
                "after_value": after,
            },
        }
