import sys
import unittest
from decimal import Decimal
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.audit import AuditService
from orbit.application.reporting import DailyReportService
from orbit.application.runtime_events import RuntimeEventService
from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine
from orbit.infrastructure.persistence.audits import InMemoryAuditRepository
from orbit.infrastructure.persistence.event_history import InMemoryEventHistoryRepository
from orbit.infrastructure.persistence.reports import InMemoryReportRepository


class FakeReportGenerator:
    def generate(self, snapshot):
        return {
            "id": "report_001",
            "date": "2026-07-10",
            "markdown_path": "reports/report.md",
        }


class ApplicationHistoryServiceTest(unittest.TestCase):
    def test_audit_service_builds_and_saves_standard_record(self):
        repository = InMemoryAuditRepository([])
        service = AuditService(repository, "strategy_001")

        audit = service.record(
            actor="admin_001",
            action_type="TEST_ACTION",
            reason="test",
            after_value={"ok": True},
        )

        self.assertIs(repository.all()[0], audit)
        self.assertEqual(audit["target_strategy_id"], "strategy_001")
        self.assertEqual(audit["admin_user_id"], "admin_001")

    def test_runtime_event_service_enriches_events_and_trades(self):
        repository = InMemoryEventHistoryRepository([], [], [])
        service = RuntimeEventService(repository, "strategy_001")
        event = {"id": "event_001", "trades": [{"id": "trade_001"}]}
        risk = {"id": "risk_001"}

        service.record_engine_results([event], [risk])

        self.assertEqual(repository.strategy_events()[0]["strategy_instance_id"], "strategy_001")
        self.assertEqual(repository.trade_events()[0]["strategy_event_id"], "event_001")
        self.assertEqual(repository.risk_events()[0]["strategy_instance_id"], "strategy_001")

    def test_sustained_block_does_not_evict_material_risk_history(self):
        repository = InMemoryEventHistoryRepository([], [], [])
        repository.add_risk_event({"id": "material", "risk_level": "critical"})
        service = RuntimeEventService(repository, "strategy_001")
        strategy = load_config(str(ROOT / "config" / "config.sample.json"))["strategy_instances"][0]
        engine = EventEngine(strategy)
        state = engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))
        state.update({
            "regime": "TRENDING",
            "regime_raw": "TRENDING",
            "regime_stable": "TRENDING",
        })

        emitted = 0
        for _ in range(250):
            events, risks = engine.execute_paper_tick(state, Decimal("61500"))
            service.record_engine_results(events, risks, account_id="acc_001")
            emitted += len(risks)

        self.assertEqual(emitted, 1)
        self.assertEqual(len(repository.risk_events()), 2)
        self.assertTrue(any(item["id"] == "material" for item in repository.risk_events()))

    def test_daily_report_service_saves_report_and_returns_audit(self):
        repository = InMemoryReportRepository([])
        service = DailyReportService(FakeReportGenerator(), repository)

        result = service.generate({}, actor="admin_001")

        self.assertTrue(result["ok"])
        self.assertEqual(repository.all()[0]["id"], "report_001")
        self.assertEqual(result["_audit"]["action_type"], "GENERATE_DAILY_REPORT")


if __name__ == "__main__":
    unittest.main()
