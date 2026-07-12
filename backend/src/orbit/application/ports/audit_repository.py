from __future__ import annotations

from typing import Any, Protocol


class AuditRepository(Protocol):
    def all(self) -> list[dict[str, Any]]:
        ...

    def add(self, audit: dict[str, Any]) -> None:
        ...

    def clear(self) -> None:
        ...
