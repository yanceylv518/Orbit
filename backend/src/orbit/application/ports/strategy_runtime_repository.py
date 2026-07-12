from __future__ import annotations

from typing import Any, Protocol


class StrategyRuntimeRepository(Protocol):
    def strategy(self) -> dict[str, Any]:
        ...

    def is_running(self) -> bool:
        ...

    def set_running(self, running: bool) -> None:
        ...
