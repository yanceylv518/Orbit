import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.account_sync import AccountSyncService
from orbit.application.permissions import PermissionPolicy
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository


class FakeSnapshotFetcher:
    def sync_account(self, account, strategy, *, mock_data_enabled=False):
        return {
            "ok": True,
            "status": "synced",
            "account_id": account["id"],
            "api_key_fingerprint": "fingerprint",
            "position_mode": {
                "dual_side_position": True,
                "hedge_mode_ok": True,
            },
            "positions": [],
        }


class FakePlanRefreshService:
    def __init__(self):
        self.account_ids = None

    def refresh(self, account_ids):
        self.account_ids = account_ids
        return [{"id": "plan_001"}]


class AccountSyncServiceTest(unittest.TestCase):
    def setUp(self):
        self.admin = {"id": "admin_001", "role": "admin"}
        self.owner = {"id": "user_001", "role": "user"}
        self.other = {"id": "user_002", "role": "user"}
        self.account = {"id": "acc_001", "user_id": "user_001"}
        self.accounts = ConfigAccountRepository({
            "users": [self.admin, self.owner, self.other],
            "exchange_accounts": [self.account],
        })
        self.snapshots = InMemoryAccountSnapshotRepository({})
        self.plan_refresh = FakePlanRefreshService()
        self.service = AccountSyncService(
            PermissionPolicy(),
            self.accounts,
            self.snapshots,
            FakeSnapshotFetcher(),
            self.plan_refresh,
            {"symbols": ["BTCUSDT"]},
            mock_data_enabled=False,
        )

    def test_fetch_rejects_unrelated_user(self):
        result = self.service.fetch(
            "acc_001",
            actor="user_002",
            actor_user=self.other,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "forbidden")

    def test_fetch_and_apply_updates_snapshot_account_and_plans(self):
        fetched = self.service.fetch(
            "acc_001",
            actor="user_001",
            actor_user=self.owner,
        )
        result = self.service.apply(fetched, actor="user_001")

        self.assertTrue(result["ok"])
        self.assertEqual(self.snapshots.get("acc_001")["status"], "synced")
        self.assertEqual(self.accounts.account_by_id("acc_001")["api_key_fingerprint"], "fingerprint")
        self.assertTrue(self.accounts.account_by_id("acc_001")["hedge_mode_enabled"])
        self.assertEqual(self.plan_refresh.account_ids, {"acc_001"})
        self.assertEqual(result["execution_plan_count"], 1)
        self.assertEqual(result["_audit"]["action_type"], "SYNC_BINANCE_ACCOUNT")

    def test_apply_rejects_account_removed_after_fetch(self):
        fetched = self.service.fetch(
            "acc_001",
            actor="admin_001",
            actor_user=self.admin,
        )
        self.accounts.accounts().clear()

        result = self.service.apply(fetched, actor="admin_001")

        self.assertFalse(result["ok"])
        self.assertIsNone(self.snapshots.get("acc_001"))


if __name__ == "__main__":
    unittest.main()
