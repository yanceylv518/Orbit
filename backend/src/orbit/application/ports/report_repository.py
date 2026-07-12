from __future__ import annotations

from typing import Any, Protocol


class ReportRepository(Protocol):
    def all(self) -> list[dict[str, Any]]:
        ...

    def add(self, report: dict[str, Any]) -> None:
        ...

    def clear(self) -> None:
        ...
