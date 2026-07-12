from __future__ import annotations

from typing import Any

from orbit.application.ports.report_generator import ReportGenerator
from orbit.application.ports.report_repository import ReportRepository


class DailyReportService:
    def __init__(self, generator: ReportGenerator, repository: ReportRepository):
        self.generator = generator
        self.repository = repository

    def generate(self, snapshot: dict[str, Any], *, actor: str) -> dict[str, Any]:
        report = self.generator.generate(snapshot)
        self.repository.add(report)
        return {
            "ok": True,
            "report": report,
            "_audit": {
                "actor": actor,
                "action_type": "GENERATE_DAILY_REPORT",
                "reason": f"生成 {report['date']} 日报。",
                "after_value": {"markdown_path": report["markdown_path"]},
            },
        }
