from __future__ import annotations

from typing import Any, Protocol


class ReportGenerator(Protocol):
    def generate(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        ...
