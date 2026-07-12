from __future__ import annotations

from typing import Any, Protocol


class SymbolStateRepository(Protocol):
    def all(self) -> dict[str, dict[str, Any]]:
        """Return all tracked symbol states keyed by symbol."""

    def replace_all(self, states: dict[str, dict[str, Any]]) -> None:
        """Replace the tracked symbol states atomically from the caller's perspective."""
