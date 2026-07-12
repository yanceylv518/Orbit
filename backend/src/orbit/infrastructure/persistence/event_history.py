from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryEventHistoryRepository:
    def __init__(
        self,
        strategy_events: list[dict[str, Any]],
        trade_events: list[dict[str, Any]],
        risk_events: list[dict[str, Any]],
    ):
        self._strategy_events = strategy_events
        self._trade_events = trade_events
        self._risk_events = risk_events

    def strategy_events(self) -> list[dict[str, Any]]:
        return self._strategy_events

    def trade_events(self) -> list[dict[str, Any]]:
        return self._trade_events

    def risk_events(self) -> list[dict[str, Any]]:
        return self._risk_events

    def add_strategy_event(self, event: dict[str, Any]) -> None:
        self._strategy_events.insert(0, event)
        del self._strategy_events[300:]

    def add_trade_event(self, event: dict[str, Any]) -> None:
        self._trade_events.insert(0, event)
        del self._trade_events[600:]

    def add_risk_event(self, event: dict[str, Any]) -> None:
        self._risk_events.insert(0, event)
        del self._risk_events[200:]

    def clear(self) -> None:
        self._strategy_events.clear()
        self._trade_events.clear()
        self._risk_events.clear()

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "strategy_events": deepcopy(self._strategy_events),
            "trade_events": deepcopy(self._trade_events),
            "risk_events": deepcopy(self._risk_events),
        }

    def restore(self, snapshot: dict[str, list[dict[str, Any]]]) -> None:
        self.clear()
        self._strategy_events.extend(deepcopy(snapshot["strategy_events"]))
        self._trade_events.extend(deepcopy(snapshot["trade_events"]))
        self._risk_events.extend(deepcopy(snapshot["risk_events"]))
