import threading
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.app_state import AppState


class RecordingExecutionService:
    def __init__(self):
        self.execution_ledger = SimpleNamespace(read_all=lambda: [])
        self.configuration = None

    def configure(self, **configuration):
        self.configuration = configuration

    def execute_due(self, sync_account):
        return {"status": "COMPLETED", "executed": True}


class LivePilotArmingTest(unittest.TestCase):
    def make_app(self):
        app = object.__new__(AppState)
        app.lock = threading.RLock()
        app.live_pilot_control = {
            "version": 1,
            "status": "PREFLIGHT_READY",
            "auto_execution_enabled": False,
            "live_account_id": "live_001",
            "max_snapshot_age_seconds": 120,
            "max_order_notional_usdt": 150,
            "round_gross_multiplier": 1.1,
        }
        app.live_execution_service = RecordingExecutionService()
        app.audit_service = SimpleNamespace(record=lambda **kwargs: None)
        app.persist = lambda: None
        return app

    def test_activation_arms_when_first_checklist_is_still_pending(self):
        app = self.make_app()
        app.run_live_pilot_preflight = lambda **kwargs: {
            "passed": True,
            "checks": [
                {
                    "code": "CHECKLIST_READY",
                    "ok": False,
                    "required": False,
                },
            ],
        }

        result = app.activate_live_pilot(
            actor="admin_001",
            execution_epoch="live-small-2026-07-31-v2",
            confirmation="ENABLE LIVE SMALL V3",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "ARMED")
        self.assertEqual(app.live_pilot_control["status"], "ARMED")
        self.assertTrue(app.live_pilot_control["auto_execution_enabled"])
        self.assertTrue(app.live_execution_service.configuration["enabled"])

    def test_permission_check_uses_minimum_compliant_order_before_checklist(self):
        app = self.make_app()
        app.trend_checklist_projector = SimpleNamespace(exchange_rules={
            "symbols": {
                "BTCUSDT": {
                    "quantity_step": "0.001",
                    "min_quantity": "0.001",
                    "min_notional_usdt": "100",
                },
            },
        })
        client = SimpleNamespace(
            ticker_price=lambda symbol: {"symbol": symbol, "price": "50000"},
        )

        params = app._live_permission_test_order(client, {"rows": []})

        self.assertEqual(params["symbol"], "BTCUSDT")
        self.assertEqual(params["quantity"], "0.003")
        self.assertGreaterEqual(
            Decimal(params["quantity"]) * Decimal("50000"),
            Decimal("110"),
        )

    def test_first_ready_checklist_transitions_armed_batch_to_active(self):
        app = self.make_app()
        app.live_pilot_control.update({
            "status": "ARMED",
            "auto_execution_enabled": True,
        })
        app.trend_forward_poll = lambda: {"ticks": 1}
        app.trend_forward_snapshot = lambda: {
            "execution_checklist": {"status": "READY"},
        }

        result = app.trend_forward_tick_once()

        self.assertEqual(result["live_execution"]["status"], "COMPLETED")
        self.assertEqual(app.live_pilot_control["status"], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
