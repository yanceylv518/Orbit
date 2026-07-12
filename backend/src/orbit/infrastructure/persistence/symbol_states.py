from __future__ import annotations

from typing import Any


class InMemorySymbolStateRepository:
    def __init__(self, states: dict[str, dict[str, Any]]):
        self.states = states

    def all(self) -> dict[str, dict[str, Any]]:
        return self.states

    def replace_all(self, states: dict[str, dict[str, Any]]) -> None:
        if states is self.states:
            return
        self.states.clear()
        self.states.update(states)
