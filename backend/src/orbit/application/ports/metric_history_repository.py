from __future__ import annotations

from typing import Any, Protocol


class MetricHistoryRepository(Protocol):
    def all(self) -> list[dict[str, Any]]:
        ...

    def by_symbol(self) -> dict[str, list[dict[str, Any]]]:
        ...

    def append_total(self, point: dict[str, Any]) -> None:
        ...

    def append_symbol(self, symbol: str, point: dict[str, Any]) -> None:
        ...

    def clear(self) -> None:
        ...
