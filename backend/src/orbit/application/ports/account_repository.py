from __future__ import annotations

from typing import Any, Protocol


class AccountRepository(Protocol):
    def users(self) -> list[dict[str, Any]]:
        ...

    def accounts(self) -> list[dict[str, Any]]:
        ...

    def user_by_id(self, user_id: str) -> dict[str, Any] | None:
        ...

    def account_by_id(self, account_id: str) -> dict[str, Any] | None:
        ...

    def save_user(self, user: dict[str, Any]) -> dict[str, Any]:
        ...

    def save_account(self, account: dict[str, Any]) -> dict[str, Any]:
        ...
