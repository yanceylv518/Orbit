from __future__ import annotations

from typing import Any

from orbit.application.execution_plans import ExecutionPlanRefreshService
from orbit.application.permissions import PermissionPolicy
from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.account_snapshot_repository import AccountSnapshotRepository
from orbit.application.ports.exchange_snapshot_fetcher import ExchangeSnapshotFetcher


class AccountSyncService:
    def __init__(
        self,
        permissions: PermissionPolicy,
        accounts: AccountRepository,
        snapshots: AccountSnapshotRepository,
        fetcher: ExchangeSnapshotFetcher,
        plan_refresh: ExecutionPlanRefreshService,
        strategy: dict[str, Any],
        *,
        mock_data_enabled: bool,
    ):
        self.permissions = permissions
        self.accounts = accounts
        self.snapshots = snapshots
        self.fetcher = fetcher
        self.plan_refresh = plan_refresh
        self.strategy = strategy
        self.mock_data_enabled = mock_data_enabled

    def fetch(
        self,
        account_id: str,
        *,
        actor: str,
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        account = self.accounts.account_by_id(account_id)
        if not account:
            return {"ok": False, "error": f"账户不存在：{account_id}"}
        if actor != "system" and not self.permissions.can_operate_account(actor_user, account):
            return {
                "ok": False,
                "status": "forbidden",
                "error": "Binance 同步只能由账户所属用户或管理员执行。",
            }
        snapshot = self.fetcher.sync_account(
            account,
            self.strategy,
            mock_data_enabled=self.mock_data_enabled,
        )
        return {"ok": True, "account_id": account_id, "snapshot": snapshot}

    def apply(self, fetched: dict[str, Any], *, actor: str) -> dict[str, Any]:
        account_id = str(fetched["account_id"])
        snapshot = fetched["snapshot"]
        account = self.accounts.account_by_id(account_id)
        if not account:
            return {"ok": False, "error": f"账户不存在：{account_id}"}

        self.snapshots.save(account_id, snapshot)
        if snapshot.get("api_key_fingerprint"):
            account["api_key_fingerprint"] = snapshot["api_key_fingerprint"]
        if snapshot.get("position_mode"):
            account["hedge_mode_enabled"] = bool(snapshot["position_mode"]["dual_side_position"])
        self.accounts.save_account(account)
        new_plans = self.plan_refresh.refresh({account_id})
        return {
            "ok": True,
            "snapshot": snapshot,
            "execution_plan_count": len(new_plans),
            "_audit": {
                "actor": actor,
                "action_type": "SYNC_BINANCE_ACCOUNT",
                "reason": f"同步 Binance 账户 {account_id} 只读数据。",
                "after_value": {
                    "account_id": account_id,
                    "status": snapshot.get("status"),
                    "hedge_mode_ok": snapshot.get("position_mode", {}).get("hedge_mode_ok"),
                    "execution_plan_count": len(new_plans),
                },
            },
        }
