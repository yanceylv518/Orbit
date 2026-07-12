from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryStrategyRuntimeRepository:
    def __init__(self, strategy: dict[str, Any], runtime_state: dict[str, Any]):
        self._strategy = strategy
        self.runtime_state = runtime_state

    def strategy(self) -> dict[str, Any]:
        return self._strategy

    def is_running(self) -> bool:
        return bool(self.runtime_state.get("running", False))

    def set_running(self, running: bool) -> None:
        self.runtime_state["running"] = bool(running)

    def snapshot(self) -> dict[str, Any]:
        return {
            "strategy": deepcopy(self._strategy),
            "running": self.is_running(),
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        self._strategy.clear()
        self._strategy.update(deepcopy(snapshot["strategy"]))
        self.set_running(bool(snapshot["running"]))
