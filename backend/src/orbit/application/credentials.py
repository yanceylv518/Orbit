from __future__ import annotations

from typing import Any

from orbit.application.permissions import PermissionPolicy
from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.credential_vault import CredentialVault, CredentialVaultError


class CredentialService:
    def __init__(
        self,
        permissions: PermissionPolicy,
        repository: AccountRepository,
        vault: CredentialVault,
    ):
        self.permissions = permissions
        self.repository = repository
        self.vault = vault

    def update_binance_credentials(
        self,
        *,
        account_id: str,
        actor: str,
        actor_user: dict[str, Any] | None,
        api_key: str,
        api_secret: str,
    ) -> dict[str, Any]:
        api_key = api_key.strip()
        api_secret = api_secret.strip()
        if not api_key or not api_secret:
            return {"ok": False, "error": "请填写 Binance API Key 和 Secret。"}
        account = self.repository.account_by_id(account_id)
        if not account:
            return {"ok": False, "error": f"账户不存在：{account_id}"}
        if not self.permissions.can_operate_account(actor_user, account):
            return {"ok": False, "error": "API Key/Secret 只能由账户所属用户或管理员维护。"}

        try:
            api_key_ref = self.vault.protect(api_key)
            secret_ref = self.vault.protect(api_secret)
        except CredentialVaultError as exc:
            return {"ok": False, "error": str(exc)}

        api_key_fingerprint = self.vault.fingerprint(api_key) or ""
        account["api_key_ref"] = api_key_ref
        account["secret_ref"] = secret_ref
        account["api_key_fingerprint"] = api_key_fingerprint
        self.repository.save_account(account)

        return {
            "ok": True,
            "account_id": account_id,
            "api_key_fingerprint": api_key_fingerprint,
            "_invalidate_snapshot": account_id,
            "_audit": {
                "actor": actor,
                "action_type": "SET_BINANCE_CREDENTIALS",
                "reason": f"更新 Binance API 凭证：{account_id}",
                "after_value": {
                    "account_id": account_id,
                    "api_key_fingerprint": api_key_fingerprint,
                },
            },
        }
