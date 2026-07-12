from __future__ import annotations

from copy import deepcopy
from typing import Any


class ConfigAccountRepository:
    """Account directory adapter backed by the loaded application config."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.config.setdefault("users", [])
        self.config.setdefault("exchange_accounts", [])

    def users(self) -> list[dict[str, Any]]:
        return self.config["users"]

    def accounts(self) -> list[dict[str, Any]]:
        return self.config["exchange_accounts"]

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        return next((user for user in self.users() if user.get("id") == user_id), None)

    def account_by_id(self, account_id: str) -> dict[str, Any] | None:
        return next((account for account in self.accounts() if account.get("id") == account_id), None)

    def save_user(self, user: dict[str, Any]) -> dict[str, Any]:
        existing = self.user_by_id(str(user["id"]))
        if existing is None:
            self.users().append(user)
            return user
        if existing is not user:
            existing.clear()
            existing.update(user)
        return existing

    def save_account(self, account: dict[str, Any]) -> dict[str, Any]:
        existing = self.account_by_id(str(account["id"]))
        if existing is None:
            self.accounts().append(account)
            return account
        if existing is not account:
            existing.clear()
            existing.update(account)
        return existing

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "users": deepcopy(self.users()),
            "exchange_accounts": deepcopy(self.accounts()),
        }

    def restore(self, snapshot: dict[str, list[dict[str, Any]]]) -> None:
        self.config["users"] = deepcopy(snapshot["users"])
        self.config["exchange_accounts"] = deepcopy(snapshot["exchange_accounts"])
