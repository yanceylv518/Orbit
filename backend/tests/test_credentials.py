import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.credentials import CredentialService
from orbit.application.permissions import PermissionPolicy
from orbit.application.ports.credential_vault import CredentialVaultError
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository


class FakeCredentialVault:
    def protect(self, value):
        return f"protected:{value}"

    def resolve(self, reference):
        return None

    def fingerprint(self, value):
        return f"fingerprint:{value}" if value else None

    def reference_name(self, reference):
        return reference


class FailingCredentialVault(FakeCredentialVault):
    def protect(self, value):
        raise CredentialVaultError("vault unavailable")


class CredentialServiceTest(unittest.TestCase):
    def setUp(self):
        self.account = {"id": "acc_001", "user_id": "user_001"}
        self.repository = ConfigAccountRepository({
            "users": [],
            "exchange_accounts": [self.account],
        })
        self.service = CredentialService(
            PermissionPolicy(),
            self.repository,
            FakeCredentialVault(),
        )
        self.admin = {"id": "admin_001", "role": "admin"}
        self.owner = {"id": "user_001", "role": "user"}
        self.other_user = {"id": "user_002", "role": "user"}

    def test_missing_credentials_are_rejected(self):
        result = self.service.update_binance_credentials(
            account_id="acc_001",
            actor="admin_001",
            actor_user=self.admin,
            api_key="",
            api_secret="secret",
        )

        self.assertFalse(result["ok"])
        self.assertNotIn("api_key_ref", self.account)

    def test_owner_can_update_credentials_in_repository(self):
        result = self.service.update_binance_credentials(
            account_id="acc_001",
            actor="user_001",
            actor_user=self.owner,
            api_key="key",
            api_secret="secret",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(self.account["api_key_ref"], "protected:key")
        self.assertEqual(self.account["secret_ref"], "protected:secret")
        self.assertEqual(self.account["api_key_fingerprint"], result["api_key_fingerprint"])
        self.assertIs(self.repository.account_by_id("acc_001"), self.account)
        self.assertEqual(result["_invalidate_snapshot"], "acc_001")
        self.assertEqual(result["_audit"]["action_type"], "SET_BINANCE_CREDENTIALS")
        self.assertNotIn("secret", str(result["_audit"]["after_value"]))

    def test_unrelated_user_cannot_update_credentials(self):
        result = self.service.update_binance_credentials(
            account_id="acc_001",
            actor="user_002",
            actor_user=self.other_user,
            api_key="key",
            api_secret="secret",
        )

        self.assertFalse(result["ok"])
        self.assertNotIn("api_key_ref", self.account)

    def test_missing_account_is_rejected(self):
        result = self.service.update_binance_credentials(
            account_id="missing",
            actor="admin_001",
            actor_user=self.admin,
            api_key="key",
            api_secret="secret",
        )

        self.assertFalse(result["ok"])

    def test_vault_error_is_returned_without_mutating_account(self):
        service = CredentialService(
            PermissionPolicy(),
            self.repository,
            FailingCredentialVault(),
        )

        result = service.update_binance_credentials(
            account_id="acc_001",
            actor="admin_001",
            actor_user=self.admin,
            api_key="key",
            api_secret="secret",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "vault unavailable")
        self.assertNotIn("api_key_ref", self.account)


if __name__ == "__main__":
    unittest.main()
