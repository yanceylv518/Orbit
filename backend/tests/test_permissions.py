import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.permissions import PermissionPolicy


class PermissionPolicyTest(unittest.TestCase):
    def test_admin_can_access_any_account(self):
        policy = PermissionPolicy()
        admin = {"id": "admin_001", "role": "admin"}
        account = {"id": "acc_001", "user_id": "user_001"}

        self.assertTrue(policy.is_admin(admin))
        self.assertTrue(policy.can_access_account(admin, account))
        self.assertTrue(policy.can_operate_account(admin, account))

    def test_business_user_is_limited_to_owned_accounts(self):
        policy = PermissionPolicy()
        user = {"id": "user_001", "role": "user"}
        owned = {"id": "acc_001", "user_id": "user_001"}
        foreign = {"id": "acc_002", "user_id": "user_002"}

        self.assertTrue(policy.is_business_user(user))
        self.assertTrue(policy.can_access_account(user, owned))
        self.assertFalse(policy.can_access_account(user, foreign))
        self.assertFalse(policy.can_manage_business_users(user))


if __name__ == "__main__":
    unittest.main()
