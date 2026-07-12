from __future__ import annotations

from typing import Any


ADMIN_ROLES = {"admin", "super_admin"}


class PermissionPolicy:
    """Single source for platform role and account visibility decisions."""

    def is_admin(self, user: dict[str, Any] | None) -> bool:
        return bool(user and user.get("role") in ADMIN_ROLES)

    def is_business_user(self, user: dict[str, Any] | None) -> bool:
        return bool(user and not self.is_admin(user))

    def can_manage_business_users(self, actor: dict[str, Any] | None) -> bool:
        return self.is_admin(actor)

    def can_manage_exchange_accounts(self, actor: dict[str, Any] | None) -> bool:
        return self.is_admin(actor)

    def can_access_account(self, actor: dict[str, Any] | None, account: dict[str, Any] | None) -> bool:
        if not actor or not account:
            return False
        return self.is_admin(actor) or account.get("user_id") == actor.get("id")

    def can_operate_account(self, actor: dict[str, Any] | None, account: dict[str, Any] | None) -> bool:
        return self.can_access_account(actor, account)

    def capabilities(self, user: dict[str, Any]) -> dict[str, bool]:
        is_admin = self.is_admin(user)
        return {
            "can_view_all_accounts": is_admin,
            "can_manage_users": is_admin,
            "can_emergency_stop": is_admin,
            "can_update_strategy": is_admin,
            "can_generate_report": is_admin,
            "can_update_account_run_config": True,
            "can_generate_execution_plan": True,
            "can_view_secret": False,
        }
