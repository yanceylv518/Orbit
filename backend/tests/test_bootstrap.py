import json
import tempfile
import unittest
from pathlib import Path

from orbit.bootstrap import create_app_state
from orbit.config import load_config


ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def make_app(self):
        tmp = tempfile.TemporaryDirectory()
        tmp_path = Path(tmp.name)
        config = load_config(str(ROOT / "config" / "config.sample.json"))
        config["runtime"]["mock_data_enabled"] = False
        config["storage"] = {
            "driver": "json",
            "json_path": str(tmp_path / "runtime_state.json"),
        }
        config["runtime"]["research"] = {
            "calibration_dir": str(tmp_path / "calibration"),
            "registry_path": str(tmp_path / "research" / "registry.jsonl"),
            "run_ledger_path": str(tmp_path / "research" / "runs.jsonl"),
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        return tmp, create_app_state(str(config_path))

    def test_container_shares_repositories_across_services_and_uow(self):
        tmp, app = self.make_app()
        try:
            self.assertIs(app.account_sync_service.snapshots, app.account_snapshot_repository)
            self.assertIs(app.execution_plan_service.plans, app.execution_plan_repository)
            self.assertIs(app.app_uow.metrics, app.metric_repository)
            self.assertIs(app.app_uow.accounts, app.account_repository)
            self.assertEqual(app.trend_forward_snapshot()["status"], "NOT_STARTED")
            self.assertEqual(app.research_catalog.datasets(), [])
        finally:
            tmp.cleanup()

    def test_factory_uses_configured_store_and_builds_public_snapshot(self):
        tmp, app = self.make_app()
        try:
            self.assertEqual(app.store.path.name, "runtime_state.json")
            snapshot = app.public_snapshot()
            self.assertFalse(snapshot["auth"]["authenticated"])
            self.assertEqual(app.config["storage"]["driver"], "json")
            admin_snapshot = app.snapshot(app.user_by_id("admin_001"))
            self.assertEqual(admin_snapshot["trend_forward"]["status"], "NOT_STARTED")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
