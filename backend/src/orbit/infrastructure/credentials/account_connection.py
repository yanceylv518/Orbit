from __future__ import annotations

from typing import Any

from orbit.application.ports.credential_vault import CredentialVault, CredentialVaultError


class VaultAccountConnectionInspector:
    def __init__(self, vault: CredentialVault):
        self.vault = vault

    def inspect(self, account: dict[str, Any]) -> dict[str, Any]:
        error = None
        try:
            key = self.vault.resolve(account.get("api_key_ref"))
            secret = self.vault.resolve(account.get("secret_ref"))
        except CredentialVaultError as exc:
            key = None
            secret = None
            error = str(exc)
        return {
            "api_key_env": self.vault.reference_name(account.get("api_key_ref")),
            "secret_env": self.vault.reference_name(account.get("secret_ref")),
            "api_key_present": bool(key),
            "secret_present": bool(secret),
            "api_key_fingerprint": self.vault.fingerprint(key),
            "credential_error": error,
        }
