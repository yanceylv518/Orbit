from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from orbit.application.auth import sanitize_user
from orbit.application.permissions import PermissionPolicy
from orbit.application.ports.account_connection_inspector import AccountConnectionInspector
from orbit.application.ports.account_repository import AccountRepository


EXTERNAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,63}$")


class AccountDirectoryService:
    def __init__(
        self,
        permissions: PermissionPolicy,
        repository: AccountRepository,
        connection_inspector: AccountConnectionInspector,
    ):
        self.permissions = permissions
        self.repository = repository
        self.connection_inspector = connection_inspector

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return self.repository.user_by_id(user_id)

    def account_by_id(self, account_id: str) -> dict[str, Any] | None:
        return self.repository.account_by_id(account_id)

    def business_users(self) -> list[dict[str, Any]]:
        return [user for user in self.repository.users() if self.permissions.is_business_user(user)]

    def is_admin_user_id(self, user_id: str) -> bool:
        return self.permissions.is_admin(self.user_by_id(user_id))

    def default_operator_user(
        self,
        auth_config: dict[str, Any],
    ) -> dict[str, Any] | None:
        users = self.repository.users()
        user_id = auth_config.get("default_operator_user_id", "admin_001")
        user = self.user_by_id(user_id)
        if user and user.get("status", "active") == "active":
            return user
        for candidate in users:
            if self.permissions.is_admin(candidate) and candidate.get("status", "active") == "active":
                return candidate
        return None

    def auth_user(self, login: str) -> dict[str, Any] | None:
        for user in self.repository.users():
            if login in (user.get("id"), user.get("email")):
                return dict(user)
        return None

    def can_access_account(
        self,
        user: dict[str, Any] | None,
        account_id: str,
    ) -> bool:
        return self.permissions.can_access_account(user, self.account_by_id(account_id))

    def can_operate_account(
        self,
        user: dict[str, Any] | None,
        account_id: str,
    ) -> bool:
        return self.permissions.can_operate_account(user, self.account_by_id(account_id))

    def visible_accounts(
        self,
        user: dict[str, Any],
    ) -> list[dict[str, Any]]:
        accounts = self.repository.accounts()
        if self.permissions.is_admin(user):
            return accounts
        user_id = user.get("id")
        return [account for account in accounts if account.get("user_id") == user_id]

    def visible_account_ids(self, user: dict[str, Any]) -> set[str]:
        return {account["id"] for account in self.visible_accounts(user)}

    def sanitize_account(self, account: dict[str, Any]) -> dict[str, Any]:
        connection = self.connection_inspector.inspect(account)
        return {
            "id": account["id"],
            "user_id": account["user_id"],
            "exchange": account.get("exchange", "binance"),
            "market_type": account.get("market_type", "futures"),
            "account_label": account.get("account_label", account["id"]),
            "testnet": bool(account.get("testnet", True)),
            "dry_run": bool(account.get("dry_run", True)),
            "hedge_mode_required": bool(account.get("hedge_mode_required", account.get("hedge_mode_enabled", False))),
            "hedge_mode_enabled": bool(account.get("hedge_mode_enabled", account.get("hedge_mode_required", False))),
            "api_key_configured": bool(account.get("api_key_ref")),
            "secret_configured": bool(account.get("secret_ref")),
            "api_key_present": connection["api_key_present"],
            "secret_present": connection["secret_present"],
            "api_key_fingerprint": connection["api_key_fingerprint"] or account.get("api_key_fingerprint"),
            "credential_error": connection.get("credential_error"),
            "status": account.get("status", "active"),
        }

    def sanitize_accounts(self, accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.sanitize_account(account) for account in accounts]


class AccountService:
    def __init__(self, permissions: PermissionPolicy, directory: AccountDirectoryService):
        self.permissions = permissions
        self.directory = directory

    def validate_external_id(self, value: str, label: str) -> str:
        value = str(value or "").strip()
        if not EXTERNAL_ID_RE.match(value):
            raise ValueError(f"{label} 只能包含字母、数字、下划线和短横线，长度 2-64 位。")
        return value

    def upsert_business_user(
        self,
        incoming: dict[str, Any],
        *,
        actor: str,
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not self.permissions.can_manage_business_users(actor_user):
            return {"ok": False, "error": "只有管理员可以维护业务用户。"}
        try:
            user_id = self.validate_external_id(str(incoming.get("user_id", "")), "用户 ID")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        name = str(incoming.get("name") or user_id).strip()
        email = str(incoming.get("email") or "").strip() or None
        status = str(incoming.get("status") or "active").strip()
        if status not in ("active", "disabled", "paused"):
            return {"ok": False, "error": "用户状态只能是 active、disabled 或 paused。"}

        existing = self.directory.user_by_id(user_id)
        if existing and self.permissions.is_admin(existing):
            return {"ok": False, "error": "管理员账号不属于业务用户，不能在这里维护。"}

        before = deepcopy(existing or {})
        if existing:
            existing.update({
                "name": name,
                "email": email,
                "role": "user",
                "status": status,
            })
            user = self.directory.repository.save_user(existing)
        else:
            user = {
                "id": user_id,
                "name": name,
                "email": email,
                "role": "user",
                "status": status,
            }
            user = self.directory.repository.save_user(user)

        return {
            "ok": True,
            "user": sanitize_user(user),
            "_audit": {
                "actor": actor,
                "action_type": "UPSERT_BUSINESS_USER",
                "reason": f"维护业务用户：{user_id}",
                "before_value": before,
                "after_value": deepcopy(user),
            },
        }

    def upsert_exchange_account(
        self,
        incoming: dict[str, Any],
        *,
        actor: str,
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not self.permissions.can_manage_exchange_accounts(actor_user):
            return {"ok": False, "error": "只有管理员可以新增或编辑交易账户。"}
        try:
            account_id = self.validate_external_id(str(incoming.get("account_id", "")), "账户 ID")
            user_id = self.validate_external_id(str(incoming.get("user_id", "")), "所属用户 ID")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}

        owner = self.directory.user_by_id(user_id)
        if not owner or not self.permissions.is_business_user(owner):
            return {"ok": False, "error": "交易账户必须绑定到一个业务用户，不能绑定管理员。"}

        status = str(incoming.get("status") or "active").strip()
        if status not in ("active", "disabled", "paused_by_admin"):
            return {"ok": False, "error": "账户状态只能是 active、disabled 或 paused_by_admin。"}

        existing = self.directory.account_by_id(account_id)
        before = deepcopy(existing or {})
        next_account = deepcopy(existing or {})
        next_account.update({
            "id": account_id,
            "user_id": user_id,
            "exchange": "binance",
            "market_type": "futures",
            "account_label": str(incoming.get("account_label") or account_id).strip(),
            "testnet": bool(incoming.get("testnet", True)),
            "dry_run": bool(incoming.get("dry_run", True)),
            "hedge_mode_required": bool(incoming.get("hedge_mode_required", True)),
            "status": status,
        })
        next_account["hedge_mode_enabled"] = bool(
            next_account.get("hedge_mode_enabled", next_account["hedge_mode_required"])
        )
        next_account.setdefault("permissions", {})

        if existing:
            existing.update(next_account)
            account = self.directory.repository.save_account(existing)
        else:
            account = next_account
            account = self.directory.repository.save_account(account)

        invalidate_snapshot = bool(before and (
            before.get("user_id") != account.get("user_id")
            or before.get("testnet") != account.get("testnet")
            or before.get("hedge_mode_required") != account.get("hedge_mode_required")
        ))
        audit_account = {
            key: value
            for key, value in account.items()
            if key not in ("api_key_ref", "secret_ref")
        }
        return {
            "ok": True,
            "account": self.directory.sanitize_account(account),
            "_audit": {
                "actor": actor,
                "action_type": "UPSERT_EXCHANGE_ACCOUNT",
                "reason": f"维护 Binance 交易账户：{account_id}",
                "before_value": before,
                "after_value": audit_account,
            },
            "_reconcile_account_runtime": True,
            "_invalidate_snapshot": account_id if invalidate_snapshot else None,
        }
