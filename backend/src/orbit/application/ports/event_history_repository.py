from __future__ import annotations

from typing import Any, Protocol


class EventHistoryRepository(Protocol):
    def strategy_events(self) -> list[dict[str, Any]]:
        ...

    def trade_events(self) -> list[dict[str, Any]]:
        ...

    def risk_events(self) -> list[dict[str, Any]]:
        ...

    def add_strategy_event(self, event: dict[str, Any]) -> None:
        ...

    def add_trade_event(self, event: dict[str, Any]) -> None:
        ...

    def add_risk_event(self, event: dict[str, Any]) -> None:
        ...

    def clear(self) -> None:
        ...
