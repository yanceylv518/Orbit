import base64
import os
from pathlib import Path
import sys
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.ports.credential_vault import CredentialVaultError
from orbit.infrastructure.credentials.aesgcm_vault import AesGcmCredentialVault
from orbit.infrastructure.credentials.factory import create_credential_vault
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault


def encoded_key(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


class AesGcmCredentialVaultTests(unittest.TestCase):
    def setUp(self):
        self.environ = {"ORBIT_CREDENTIAL_MASTER_KEY": encoded_key(bytes(range(32)))}
        self.vault = AesGcmCredentialVault(environ=self.environ)

    def test_round_trip_uses_random_nonce_and_never_exposes_plaintext(self):
        first = self.vault.protect("binance-secret")
        second = self.vault.protect("binance-secret")

        self.assertTrue(first.startswith("aesgcm:v1:"))
        self.assertNotEqual(first, second)
        self.assertNotIn("binance-secret", first)
        self.assertEqual(self.vault.resolve(first), "binance-secret")
        self.assertEqual(self.vault.reference_name(first), "account_credential")

    def test_tampered_ciphertext_and_wrong_key_are_rejected(self):
        reference = self.vault.protect("secret")
        replacement = "A" if reference[-1] != "A" else "B"

        with self.assertRaisesRegex(CredentialVaultError, "Failed to decrypt"):
            self.vault.resolve(reference[:-1] + replacement)
        wrong = AesGcmCredentialVault(environ={
            "ORBIT_CREDENTIAL_MASTER_KEY": encoded_key(os.urandom(32)),
        })
        with self.assertRaisesRegex(CredentialVaultError, "Failed to decrypt"):
            wrong.resolve(reference)

    def test_missing_master_key_blocks_encryption_but_env_references_still_work(self):
        vault = AesGcmCredentialVault(environ={"BINANCE_API_KEY": "key-from-env"})

        self.assertEqual(vault.resolve("env:BINANCE_API_KEY"), "key-from-env")
        with self.assertRaisesRegex(CredentialVaultError, "ORBIT_CREDENTIAL_MASTER_KEY"):
            vault.protect("secret")

    def test_windows_dpapi_reference_has_clear_migration_error(self):
        with self.assertRaisesRegex(CredentialVaultError, "DPAPI"):
            self.vault.resolve("dpapi:AAAA")

    def test_unknown_aesgcm_version_is_rejected(self):
        with self.assertRaisesRegex(CredentialVaultError, "Unsupported AES-GCM"):
            self.vault.resolve("aesgcm:v2:AAAA")


class CredentialVaultFactoryTests(unittest.TestCase):
    def test_auto_selects_aesgcm_on_linux_and_dpapi_on_windows(self):
        config = {"runtime": {"credentials": {"driver": "auto"}}}

        linux = create_credential_vault(config, platform="linux", environ=self._key_environ())
        windows = create_credential_vault(config, platform="win32")

        self.assertIsInstance(linux, AesGcmCredentialVault)
        self.assertIsInstance(windows, LocalCredentialVault)
        self.assertEqual(linux.resolve(linux.protect("secret")), "secret")

    def test_explicit_dpapi_is_rejected_on_linux(self):
        config = {"runtime": {"credentials": {"driver": "dpapi"}}}

        with self.assertRaisesRegex(CredentialVaultError, "Windows only"):
            create_credential_vault(config, platform="linux")

    @staticmethod
    def _key_environ():
        return {"ORBIT_CREDENTIAL_MASTER_KEY": encoded_key(bytes(range(32)))}


if __name__ == "__main__":
    unittest.main()
