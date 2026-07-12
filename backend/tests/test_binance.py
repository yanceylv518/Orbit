import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.credentials.account_connection import VaultAccountConnectionInspector
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault
from orbit.application.ports.credential_vault import CredentialVaultError


class FailingResolveVault(LocalCredentialVault):
    def resolve(self, reference):
        raise CredentialVaultError("cannot decrypt")


class CredentialAdapterTest(unittest.TestCase):
    def test_fingerprint_is_short_and_stable(self):
        vault = LocalCredentialVault()
        self.assertEqual(vault.fingerprint("abc"), vault.fingerprint("abc"))
        self.assertEqual(len(vault.fingerprint("abc")), 16)

    def test_account_connection_flags_use_env_refs(self):
        account = {
            "api_key_ref": "env:DDG_TEST_MISSING_KEY",
            "secret_ref": "env:DDG_TEST_MISSING_SECRET",
        }
        status = VaultAccountConnectionInspector(LocalCredentialVault()).inspect(account)
        self.assertFalse(status["api_key_present"])
        self.assertFalse(status["secret_present"])
        self.assertEqual(status["api_key_env"], "DDG_TEST_MISSING_KEY")

    def test_account_connection_reports_vault_errors(self):
        account = {"api_key_ref": "dpapi:key", "secret_ref": "dpapi:secret"}

        status = VaultAccountConnectionInspector(FailingResolveVault()).inspect(account)

        self.assertFalse(status["api_key_present"])
        self.assertFalse(status["secret_present"])
        self.assertEqual(status["credential_error"], "cannot decrypt")


if __name__ == "__main__":
    unittest.main()
