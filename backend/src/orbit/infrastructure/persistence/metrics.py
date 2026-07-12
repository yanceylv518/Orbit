from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryMetricHistoryRepository:
    def __init__(self, totals: list[dict[str, Any]], symbols: dict[str, list[dict[str, Any]]], limit: int = 500):
        self.totals = totals
        self.symbols = symbols
        self.limit = limit

    def all(self) -> list[dict[str, Any]]:
        return self.totals

    def by_symbol(self) -> dict[str, list[dict[str, Any]]]:
        return self.symbols

    def append_total(self, point: dict[str, Any]) -> None:
        self.totals.append(point)
        del self.totals[:-self.limit]

    def append_symbol(self, symbol: str, point: dict[str, Any]) -> None:
        history = self.symbols.setdefault(symbol, [])
        history.append(point)
        del history[:-self.limit]

    def clear(self) -> None:
        self.totals.clear()
        self.symbols.clear()

    def snapshot(self) -> dict[str, Any]:
        return {"totals": deepcopy(self.totals), "symbols": deepcopy(self.symbols)}

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.clear()
        self.totals.extend(deepcopy(snapshot["totals"]))
        self.symbols.update(deepcopy(snapshot["symbols"]))
