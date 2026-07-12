from __future__ import annotations

from typing import Any, Protocol


class AccountSnapshotRepository(Protocol):
    def all(self) -> dict[str, dict[str, Any]]:
        ...

    def get(self, account_id: str) -> dict[str, Any] | None:
        ...

    def save(self, account_id: str, snapshot: dict[str, Any]) -> None:
        ...

    def delete(self, account_id: str) -> None:
        ...

    def clear(self) -> None:
        ...
