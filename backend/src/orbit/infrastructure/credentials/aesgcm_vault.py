from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from orbit.application.ports.credential_vault import CredentialVaultError


AESGCM_PREFIX = "aesgcm:v1:"
ENV_PREFIX = "env:"
ASSOCIATED_DATA = b"orbit-binance-credentials-v1"


class AesGcmCredentialVault:
    """Cross-platform vault backed by an environment-supplied AES-256 key."""

    def __init__(
        self,
        master_key_env: str = "ORBIT_CREDENTIAL_MASTER_KEY",
        environ: Mapping[str, str] | None = None,
    ):
        self.master_key_env = master_key_env
        self.environ = environ if environ is not None else os.environ

    def protect(self, value: str) -> str:
        nonce = os.urandom(12)
        encrypted = AESGCM(self._master_key()).encrypt(nonce, value.encode("utf-8"), ASSOCIATED_DATA)
        return AESGCM_PREFIX + base64.urlsafe_b64encode(nonce + encrypted).decode("ascii")

    def resolve(self, reference: str | None) -> str | None:
        if not reference:
            return None
        if reference.startswith(AESGCM_PREFIX):
            return self._unprotect(reference)
        if reference.startswith("aesgcm:"):
            raise CredentialVaultError("Unsupported AES-GCM credential reference version.")
        if reference.startswith("dpapi:"):
            raise CredentialVaultError(
                "Windows DPAPI credential cannot be decrypted by the AES-GCM vault; re-enter the account credential."
            )
        return self.environ.get(reference.removeprefix(ENV_PREFIX))

    @staticmethod
    def fingerprint(value: str | None) -> str | None:
        if not value:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def reference_name(reference: str | None) -> str | None:
        if not reference:
            return None
        if reference.startswith(AESGCM_PREFIX):
            return "account_credential"
        return reference.removeprefix(ENV_PREFIX)

    def _unprotect(self, reference: str) -> str:
        try:
            raw = base64.b64decode(
                reference.removeprefix(AESGCM_PREFIX).encode("ascii"),
                altchars=b"-_",
                validate=True,
            )
            if len(raw) < 12 + 16:
                raise ValueError("encrypted credential payload is too short")
            return AESGCM(self._master_key()).decrypt(raw[:12], raw[12:], ASSOCIATED_DATA).decode("utf-8")
        except (InvalidTag, ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise CredentialVaultError("Failed to decrypt credential with AES-GCM.") from exc

    def _master_key(self) -> bytes:
        encoded = self.environ.get(self.master_key_env, "").strip()
        if not encoded:
            raise CredentialVaultError(
                f"Set {self.master_key_env} to a URL-safe base64 encoded 32-byte key before saving credentials."
            )
        try:
            key = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise CredentialVaultError(f"{self.master_key_env} is not valid URL-safe base64.") from exc
        if len(key) != 32:
            raise CredentialVaultError(f"{self.master_key_env} must decode to exactly 32 bytes.")
        return key
