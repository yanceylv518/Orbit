import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.account_runtime import AccountRunConfigService
from orbit.application.permissions import PermissionPolicy
from orbit.config import load_config
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository


class AccountRunConfigServiceTest(unittest.TestCase):
    def setUp(self):
        config = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = config["strategy_instances"][0]
        self.admin = {"id": "admin_001", "role": "admin", "status": "active"}
        self.owner = {"id": "user_001", "role": "user", "status": "active"}
        self.other = {"id": "user_002", "role": "user", "status": "active"}
        self.account = {"id": "acc_001", "user_id": "user_001"}
        self.app_config = {
            "users": [self.admin, self.owner, self.other],
            "exchange_accounts": [self.account],
        }
        self.accounts = ConfigAccountRepository(self.app_config)
        self.configs = InMemoryRunConfigRepository([], self.app_config)
        self.service = AccountRunConfigService(
            PermissionPolicy(),
            self.accounts,
            self.configs,
            self.strategy,
        )

    def test_ensure_all_creates_one_config_per_account(self):
        self.service.ensure_all()

        config = self.configs.get("acc_001")
        self.assertIsNotNone(config)
        self.assertEqual(config["mode"], "plan_only")
        self.assertEqual(config["interval"], "1h")
        self.assertFalse(config["allow_market_orders"])
        self.assertIs(self.app_config["account_run_configs"], self.configs.all())

    def test_owner_update_is_normalized_and_audited(self):
        result = self.service.update(
            "acc_001",
            {
                "symbols": ["btcusdt", ""],
                "max_single_order_usdt": -10,
                "allow_market_orders": True,
                "interval": "15m",
            },
            actor="user_001",
            actor_user=self.owner,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["run_config"]["symbols"], ["BTCUSDT"])
        self.assertEqual(result["run_config"]["max_single_order_usdt"], 0)
        self.assertFalse(result["run_config"]["allow_market_orders"])
        self.assertEqual(result["run_config"]["interval"], "15m")
        self.assertEqual(result["_audit"]["action_type"], "UPDATE_ACCOUNT_RUN_CONFIG")

    def test_unrelated_user_cannot_update_config(self):
        result = self.service.update(
            "acc_001",
            {"enabled": False},
            actor="user_002",
            actor_user=self.other,
        )

        self.assertFalse(result["ok"])
        self.assertIsNone(self.configs.get("acc_001"))

    def test_ensure_all_removes_orphaned_configs(self):
        self.configs.save({"id": "run_missing", "account_id": "missing"})

        self.service.ensure_all()

        self.assertIsNone(self.configs.get("missing"))
        self.assertIsNotNone(self.configs.get("acc_001"))


if __name__ == "__main__":
    unittest.main()
