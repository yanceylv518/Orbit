import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.accounts import AccountDirectoryService, AccountService
from orbit.application.permissions import PermissionPolicy
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.credentials.account_connection import VaultAccountConnectionInspector
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault


class AccountDirectoryServiceTest(unittest.TestCase):
    def setUp(self):
        self.users = [
            {"id": "admin_001", "name": "Admin", "role": "admin", "status": "active"},
            {"id": "user_001", "name": "Alice", "role": "user", "status": "active", "email": "a@example.com"},
            {"id": "user_002", "name": "Bob", "role": "user", "status": "disabled"},
        ]
        self.accounts = [
            {
                "id": "acc_001",
                "user_id": "user_001",
                "account_label": "Alice Binance",
                "api_key_ref": "env:ORBIT_TEST_ACCOUNT_KEY",
                "secret_ref": "env:ORBIT_TEST_ACCOUNT_SECRET",
                "api_key_fingerprint": "stored",
            },
            {"id": "acc_002", "user_id": "user_002", "account_label": "Bob Binance"},
        ]
        self.repository = ConfigAccountRepository({
            "users": self.users,
            "exchange_accounts": self.accounts,
        })
        self.service = AccountDirectoryService(
            PermissionPolicy(),
            self.repository,
            VaultAccountConnectionInspector(LocalCredentialVault()),
        )

    def test_default_operator_prefers_active_configured_admin(self):
        user = self.service.default_operator_user(
            {"default_operator_user_id": "admin_001"},
        )

        self.assertEqual(user["id"], "admin_001")

    def test_auth_user_uses_id_or_email(self):
        self.assertEqual(self.service.auth_user("user_001")["id"], "user_001")
        self.assertEqual(self.service.auth_user("a@example.com")["id"], "user_001")
        self.assertIsNone(self.service.auth_user("missing@example.com"))

    def test_visibility_and_account_permissions(self):
        admin = self.service.user_by_id("admin_001")
        owner = self.service.user_by_id("user_001")

        self.assertEqual(
            {account["id"] for account in self.service.visible_accounts(admin)},
            {"acc_001", "acc_002"},
        )
        self.assertEqual(self.service.visible_account_ids(owner), {"acc_001"})
        self.assertTrue(self.service.can_access_account(owner, "acc_001"))
        self.assertFalse(self.service.can_access_account(owner, "acc_002"))

    def test_sanitize_account_hides_secret_refs(self):
        with patch.dict(
            os.environ,
            {"ORBIT_TEST_ACCOUNT_KEY": "key", "ORBIT_TEST_ACCOUNT_SECRET": "secret"},
            clear=False,
        ):
            account = self.service.sanitize_account(self.accounts[0])

        self.assertTrue(account["api_key_present"])
        self.assertTrue(account["secret_present"])
        self.assertNotIn("api_key_ref", account)
        self.assertNotIn("secret_ref", account)
        self.assertEqual(len(account["api_key_fingerprint"]), 16)


class AccountServiceTest(unittest.TestCase):
    def setUp(self):
        self.permissions = PermissionPolicy()
        self.users = [
            {"id": "admin_001", "name": "Admin", "role": "admin", "status": "active"},
            {"id": "user_001", "name": "Alice", "role": "user", "status": "active"},
        ]
        self.accounts = [
            {
                "id": "acc_001",
                "user_id": "user_001",
                "account_label": "Alice Binance",
                "testnet": True,
                "dry_run": True,
                "hedge_mode_required": True,
            }
        ]
        self.repository = ConfigAccountRepository({
            "users": self.users,
            "exchange_accounts": self.accounts,
        })
        self.directory = AccountDirectoryService(
            self.permissions,
            self.repository,
            VaultAccountConnectionInspector(LocalCredentialVault()),
        )
        self.service = AccountService(self.permissions, self.directory)

    def test_only_admin_can_upsert_business_user(self):
        user = self.directory.user_by_id("user_001")
        result = self.service.upsert_business_user(
            {"user_id": "user_002", "name": "Bob"},
            actor="user_001",
            actor_user=user,
        )

        self.assertFalse(result["ok"])
        self.assertIsNone(self.directory.user_by_id("user_002"))

    def test_admin_can_upsert_business_user_with_audit(self):
        admin = self.directory.user_by_id("admin_001")
        result = self.service.upsert_business_user(
            {
                "user_id": "user_002",
                "name": "Bob",
                "email": "bob@example.com",
                "status": "active",
            },
            actor="admin_001",
            actor_user=admin,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["user"]["id"], "user_002")
        self.assertEqual(self.directory.user_by_id("user_002")["role"], "user")
        self.assertEqual(result["_audit"]["action_type"], "UPSERT_BUSINESS_USER")

    def test_exchange_account_must_belong_to_business_user(self):
        admin = self.directory.user_by_id("admin_001")
        result = self.service.upsert_exchange_account(
            {
                "account_id": "acc_admin",
                "user_id": "admin_001",
                "account_label": "Wrong Owner",
            },
            actor="admin_001",
            actor_user=admin,
        )

        self.assertFalse(result["ok"])
        self.assertIsNone(self.directory.account_by_id("acc_admin"))

    def test_exchange_account_upsert_marks_snapshot_invalidation(self):
        admin = self.directory.user_by_id("admin_001")
        result = self.service.upsert_exchange_account(
            {
                "account_id": "acc_001",
                "user_id": "user_001",
                "account_label": "Alice Binance Live",
                "testnet": False,
                "dry_run": True,
                "hedge_mode_required": True,
                "status": "active",
            },
            actor="admin_001",
            actor_user=admin,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["_invalidate_snapshot"], "acc_001")
        self.assertTrue(result["_reconcile_account_runtime"])
        self.assertEqual(result["_audit"]["action_type"], "UPSERT_EXCHANGE_ACCOUNT")
        self.assertFalse(self.directory.account_by_id("acc_001")["testnet"])
        self.assertNotIn("secret_ref", result["account"])


if __name__ == "__main__":
    unittest.main()
