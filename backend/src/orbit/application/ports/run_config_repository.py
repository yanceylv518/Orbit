from __future__ import annotations

from typing import Any, Protocol


class RunConfigRepository(Protocol):
    def all(self) -> list[dict[str, Any]]:
        ...

    def get(self, account_id: str) -> dict[str, Any] | None:
        ...

    def save(self, config: dict[str, Any]) -> dict[str, Any]:
        ...

    def replace_all(self, configs: list[dict[str, Any]]) -> None:
        ...
