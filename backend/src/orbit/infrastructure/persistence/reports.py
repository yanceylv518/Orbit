from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryReportRepository:
    def __init__(self, reports: list[dict[str, Any]], limit: int = 30):
        self.reports = reports
        self.limit = limit

    def all(self) -> list[dict[str, Any]]:
        return self.reports

    def add(self, report: dict[str, Any]) -> None:
        self.reports.insert(0, report)
        del self.reports[self.limit:]

    def clear(self) -> None:
        self.reports.clear()

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self.reports)

    def restore(self, reports: list[dict[str, Any]]) -> None:
        self.reports.clear()
        self.reports.extend(deepcopy(reports[:self.limit]))
