import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.strategy_control import StrategyControlService
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.strategy_runtime import InMemoryStrategyRuntimeRepository


class StrategyControlServiceTest(unittest.TestCase):
    def setUp(self):
        self.strategy = {"id": "strategy_001", "status": "paused"}
        self.runtime = InMemoryStrategyRuntimeRepository(self.strategy, {"running": False})
        self.accounts = ConfigAccountRepository({
            "users": [],
            "exchange_accounts": [
                {"id": "acc_001", "user_id": "user_001", "status": "active"},
                {"id": "acc_002", "user_id": "user_002", "status": "disabled"},
            ],
        })
        self.service = StrategyControlService(self.runtime, self.accounts)

    def test_set_running_updates_runtime_and_audit(self):
        result = self.service.set_running(True, actor="admin_001")

        self.assertTrue(self.runtime.is_running())
        self.assertEqual(self.strategy["status"], "running")
        self.assertEqual(result["_audit"]["action_type"], "START_STRATEGY")

    def test_emergency_stop_pauses_all_accounts(self):
        result = self.service.emergency_stop(actor="admin_001")

        self.assertFalse(self.runtime.is_running())
        self.assertEqual(self.strategy["status"], "emergency_stopped")
        self.assertTrue(all(
            account["status"] == "paused_by_admin"
            for account in self.accounts.accounts()
        ))
        self.assertEqual(result["_audit"]["action_type"], "GLOBAL_EMERGENCY_STOP")

    def test_resume_only_reactivates_admin_paused_accounts(self):
        self.accounts.account_by_id("acc_001")["status"] = "paused_by_admin"

        result = self.service.resume(actor="admin_001")

        self.assertTrue(self.runtime.is_running())
        self.assertEqual(self.accounts.account_by_id("acc_001")["status"], "active")
        self.assertEqual(self.accounts.account_by_id("acc_002")["status"], "disabled")
        self.assertEqual(result["_audit"]["action_type"], "RESUME_AFTER_EMERGENCY_STOP")


if __name__ == "__main__":
    unittest.main()
