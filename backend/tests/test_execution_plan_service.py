import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.execution_plans import ExecutionPlanService
from orbit.application.permissions import PermissionPolicy
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.execution_plans import InMemoryExecutionPlanRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository


class ExecutionPlanServiceTest(unittest.TestCase):
    def setUp(self):
        self.owner = {"id": "user_001", "role": "user", "status": "active"}
        self.other_user = {"id": "user_002", "role": "user", "status": "active"}
        self.account = {"id": "acc_001", "user_id": "user_001"}
        self.plan = {
            "id": "plan_001",
            "account_id": "acc_001",
            "symbol": "BTCUSDT",
            "event_type": "PROFIT_TRANSFER",
            "status": "planned",
        }
        self.accounts = ConfigAccountRepository({
            "users": [self.owner, self.other_user],
            "exchange_accounts": [self.account],
        })
        self.plans = InMemoryExecutionPlanRepository([self.plan])
        self.run_configs = InMemoryRunConfigRepository([], {})
        self.snapshots = InMemoryAccountSnapshotRepository({})
        self.service = ExecutionPlanService(
            PermissionPolicy(),
            self.accounts,
            self.run_configs,
            self.snapshots,
            self.plans,
        )

    def test_owner_confirmation_is_saved_through_repository(self):
        result = self.service.confirm(
            plan_id="plan_001",
            actor="user_001",
            actor_user=self.owner,
            note="checked",
        )

        self.assertTrue(result["ok"])
        saved = self.plans.get("plan_001")
        self.assertEqual(saved["manual_review"]["status"], "confirmed")
        self.assertEqual(result["_audit"]["action_type"], "CONFIRM_EXECUTION_PLAN")

    def test_unrelated_user_cannot_confirm_plan(self):
        result = self.service.confirm(
            plan_id="plan_001",
            actor="user_002",
            actor_user=self.other_user,
            note=None,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "forbidden")
        self.assertNotIn("manual_review", self.plans.get("plan_001"))

    def test_export_marks_selected_plan_in_repository(self):
        result = self.service.record_export(
            plan_ids=["plan_001"],
            actor="user_001",
            actor_user=self.owner,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(self.plans.get("plan_001")["last_export"]["id"], result["export_id"])
        self.assertEqual(result["_audit"]["action_type"], "EXPORT_EXECUTION_PLANS")


if __name__ == "__main__":
    unittest.main()
