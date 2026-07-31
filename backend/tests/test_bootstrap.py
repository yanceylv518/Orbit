import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.bootstrap import create_app_state
from orbit.application.app_state import AppState
from orbit.bootstrap import DefaultApplicationBootstrap
from orbit.config import load_config
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC


ROOT = Path(__file__).resolve().parents[2]


class PreparingBinanceClient:
    calls = []
    leverage = {}

    @classmethod
    def from_account(cls, account, vault):
        cls.calls.append(("account", account["id"], account["testnet"]))
        return cls()

    def open_orders(self):
        return []

    def position_risk(self):
        return [
            {
                "symbol": symbol,
                "positionAmt": "0",
            }
            for symbol in TB4_SPEC.symbols
        ]

    def symbol_configuration(self):
        return [
            {
                "symbol": symbol,
                "leverage": str(self.leverage.get(symbol, 20)),
            }
            for symbol in TB4_SPEC.symbols
        ]

    def position_mode(self):
        return {"dualSidePosition": True}

    def change_position_mode(self, *, dual_side):
        self.calls.append(("position_mode", dual_side))
        return {"code": 200}

    def change_leverage(self, symbol, leverage):
        self.calls.append(("leverage", symbol, leverage))
        self.leverage[symbol] = leverage
        return {"symbol": symbol, "leverage": leverage}


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
            self.assertEqual(
                app.trend_forward_snapshot()["execution_checklist"]["capital_usdt"],
                500.0,
            )
            self.assertEqual(
                app.live_reconciliation_service.snapshot()["status"],
                "ACCOUNT_NOT_CONFIGURED",
            )
            self.assertEqual(
                app.live_execution_service.snapshot()["status"],
                "DISABLED",
            )
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
            self.assertFalse(
                admin_snapshot["trend_forward"]["execution_checklist"]["live_trading"],
            )
            self.assertEqual(
                admin_snapshot["live_reconciliation"]["status"],
                "ACCOUNT_NOT_CONFIGURED",
            )
            self.assertEqual(admin_snapshot["live_execution"]["status"], "DISABLED")
        finally:
            tmp.cleanup()

    def test_live_pilot_control_is_restored_and_applied_after_restart(self):
        tmp, app = self.make_app()
        try:
            configured = app.configure_live_pilot(
                actor="admin_001",
                account_id="binance_dry_run_001",
            )
            self.assertTrue(configured["ok"])

            restored = create_app_state(str(Path(tmp.name) / "config.json"))

            self.assertEqual(
                restored.live_pilot_control["live_account_id"],
                "binance_dry_run_001",
            )
            self.assertEqual(
                restored.live_reconciliation_service.live_account_id,
                "binance_dry_run_001",
            )
            self.assertEqual(
                restored.live_execution_service.live_account_id,
                "binance_dry_run_001",
            )
            self.assertFalse(restored.live_execution_service.enabled)
        finally:
            tmp.cleanup()

    def test_prepare_live_account_changes_binance_before_opening_orbit_live_mode(self):
        tmp, app = self.make_app()
        try:
            PreparingBinanceClient.calls = []
            PreparingBinanceClient.leverage = {}
            app.configure_live_pilot(
                actor="admin_001",
                account_id="binance_dry_run_001",
            )

            with patch(
                "orbit.application.app_state.BinanceFuturesClient",
                PreparingBinanceClient,
            ):
                result = app.prepare_live_pilot_account(
                    actor="admin_001",
                    account_id="binance_dry_run_001",
                    confirmation="PREPARE LIVE ACCOUNT",
                )

            self.assertTrue(result["ok"])
            account = app.account_by_id("binance_dry_run_001")
            self.assertFalse(account["testnet"])
            self.assertFalse(account["dry_run"])
            self.assertIn(("position_mode", False), PreparingBinanceClient.calls)
            leverage_calls = [
                item for item in PreparingBinanceClient.calls
                if item[0] == "leverage"
            ]
            self.assertEqual(len(leverage_calls), len(TB4_SPEC.symbols))
            self.assertTrue(all(item[2] == 1 for item in leverage_calls))
        finally:
            tmp.cleanup()

    def test_authoritative_directory_fails_fast_when_incomplete(self):
        class IncompleteStore:
            directory_authoritative = True

            def load_directory(self):
                return {
                    "users": [{"id": "admin_001", "role": "admin", "status": "active"}],
                    "exchange_accounts": [],
                    "strategy_instances": [],
                    "account_run_configs": [],
                }

        class Bootstrap(DefaultApplicationBootstrap):
            def create_state_store(self, root, config):
                return IncompleteStore()

        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "config.json"
            config = load_config(str(ROOT / "config" / "config.sample.json"))
            config["auth"]["login_required"] = True
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "MySQL directory is incomplete"):
                AppState(Bootstrap(), str(path))
        finally:
            tmp.cleanup()

    def test_authoritative_directory_requires_active_admin(self):
        class NoAdminStore:
            directory_authoritative = True

            def load_directory(self):
                return {
                    "users": [{"id": "owner_001", "role": "user", "status": "active"}],
                    "exchange_accounts": [{"id": "account_001"}],
                    "strategy_instances": [{"id": "strategy_001"}],
                    "account_run_configs": [],
                }

        class Bootstrap(DefaultApplicationBootstrap):
            def create_state_store(self, root, config):
                return NoAdminStore()

        tmp = tempfile.TemporaryDirectory()
        try:
            path = Path(tmp.name) / "config.json"
            config = load_config(str(ROOT / "config" / "config.sample.json"))
            config["auth"]["login_required"] = True
            path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "no active administrator"):
                AppState(Bootstrap(), str(path))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
