import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.audits import InMemoryAuditRepository
from orbit.infrastructure.persistence.execution_plans import InMemoryExecutionPlanRepository
from orbit.infrastructure.persistence.event_history import InMemoryEventHistoryRepository
from orbit.infrastructure.persistence.reports import InMemoryReportRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository
from orbit.infrastructure.persistence.strategy_runtime import InMemoryStrategyRuntimeRepository
from orbit.infrastructure.persistence.metrics import InMemoryMetricHistoryRepository
from orbit.infrastructure.persistence.unit_of_work import InMemoryApplicationUnitOfWork


class InMemoryApplicationUnitOfWorkTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "users": [{"id": "user_001", "role": "user"}],
            "exchange_accounts": [{"id": "acc_001", "user_id": "user_001"}],
        }
        self.accounts = ConfigAccountRepository(self.config)
        self.run_configs = InMemoryRunConfigRepository([], self.config)
        self.snapshots = InMemoryAccountSnapshotRepository({})
        self.symbol_states = InMemorySymbolStateRepository({"BTCUSDT": {"state": "BALANCED"}})
        self.plans = InMemoryExecutionPlanRepository([{"id": "plan_001", "status": "planned"}])
        self.audits = InMemoryAuditRepository([])
        self.events = InMemoryEventHistoryRepository([], [], [])
        self.reports = InMemoryReportRepository([])
        self.strategy_runtime = InMemoryStrategyRuntimeRepository(
            {"id": "strategy_001", "status": "paused"},
            {"running": False},
        )
        self.metrics = InMemoryMetricHistoryRepository([], {})

    def make_uow(self, callback):
        return InMemoryApplicationUnitOfWork(
            self.accounts,
            self.run_configs,
            self.snapshots,
            self.symbol_states,
            self.plans,
            self.audits,
            self.events,
            self.reports,
            self.strategy_runtime,
            self.metrics,
            callback,
        )

    def mutate_all_repositories(self):
        self.accounts.save_user({"id": "user_002", "role": "user"})
        self.run_configs.save({"id": "run_acc_001", "account_id": "acc_001"})
        self.snapshots.save("acc_001", {"status": "synced"})
        self.symbol_states.all()["BTCUSDT"]["state"] = "TREND_UP"
        self.plans.get("plan_001")["manual_review"] = {"status": "confirmed"}
        self.audits.add({"id": "audit_001"})
        self.events.add_risk_event({"id": "risk_001"})
        self.reports.add({"id": "report_001"})
        self.strategy_runtime.set_running(True)
        self.strategy_runtime.strategy()["status"] = "running"
        self.metrics.append_total({"tick": 1})

    def test_commit_keeps_all_repository_changes(self):
        commits = []
        with self.make_uow(lambda: commits.append("saved")) as uow:
            self.mutate_all_repositories()
            uow.commit()

        self.assertEqual(commits, ["saved"])
        self.assertIsNotNone(self.accounts.user_by_id("user_002"))
        self.assertIsNotNone(self.run_configs.get("acc_001"))
        self.assertEqual(self.snapshots.get("acc_001")["status"], "synced")
        self.assertEqual(self.symbol_states.all()["BTCUSDT"]["state"], "TREND_UP")
        self.assertEqual(self.plans.get("plan_001")["manual_review"]["status"], "confirmed")
        self.assertEqual(self.audits.all()[0]["id"], "audit_001")
        self.assertEqual(self.events.risk_events()[0]["id"], "risk_001")
        self.assertEqual(self.reports.all()[0]["id"], "report_001")
        self.assertTrue(self.strategy_runtime.is_running())
        self.assertEqual(self.metrics.all()[0]["tick"], 1)

    def test_uncommitted_changes_are_rolled_back(self):
        with self.make_uow(lambda: None):
            self.mutate_all_repositories()

        self.assertIsNone(self.accounts.user_by_id("user_002"))
        self.assertIsNone(self.run_configs.get("acc_001"))
        self.assertIsNone(self.snapshots.get("acc_001"))
        self.assertEqual(self.symbol_states.all()["BTCUSDT"]["state"], "BALANCED")
        self.assertNotIn("manual_review", self.plans.get("plan_001"))
        self.assertEqual(self.audits.all(), [])
        self.assertEqual(self.events.risk_events(), [])
        self.assertEqual(self.reports.all(), [])
        self.assertFalse(self.strategy_runtime.is_running())
        self.assertEqual(self.strategy_runtime.strategy()["status"], "paused")
        self.assertEqual(self.metrics.all(), [])

    def test_failed_commit_rolls_back_all_repositories(self):
        def fail_save():
            raise RuntimeError("save failed")

        with self.assertRaises(RuntimeError):
            with self.make_uow(fail_save) as uow:
                self.mutate_all_repositories()
                uow.commit()

        self.assertIsNone(self.accounts.user_by_id("user_002"))
        self.assertIsNone(self.run_configs.get("acc_001"))
        self.assertIsNone(self.snapshots.get("acc_001"))
        self.assertEqual(self.symbol_states.all()["BTCUSDT"]["state"], "BALANCED")
        self.assertNotIn("manual_review", self.plans.get("plan_001"))
        self.assertEqual(self.audits.all(), [])
        self.assertEqual(self.events.risk_events(), [])
        self.assertEqual(self.reports.all(), [])
        self.assertFalse(self.strategy_runtime.is_running())
        self.assertEqual(self.strategy_runtime.strategy()["status"], "paused")
        self.assertEqual(self.metrics.all(), [])


if __name__ == "__main__":
    unittest.main()
