from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryAuditRepository:
    def __init__(self, audits: list[dict[str, Any]], limit: int = 300):
        self.audits = audits
        self.limit = limit

    def all(self) -> list[dict[str, Any]]:
        return self.audits

    def add(self, audit: dict[str, Any]) -> None:
        self.audits.insert(0, audit)
        del self.audits[self.limit:]

    def clear(self) -> None:
        self.audits.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self.audits)

    def restore(self, audits: list[dict[str, Any]]) -> None:
        self.audits.clear()
        self.audits.extend(deepcopy(audits[:self.limit]))
