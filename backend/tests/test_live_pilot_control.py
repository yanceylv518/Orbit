import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.live_pilot_control import (
    default_live_pilot_control,
    normalize_live_pilot_control,
    project_preflight,
    validate_epoch,
)


class LivePilotControlTest(unittest.TestCase):
    def test_legacy_runtime_is_migrated_into_persistent_control(self):
        control = default_live_pilot_control({
            "trend_forward": {
                "enabled": True,
                "live_account_id": "live_001",
                "live_capital_usdt": 500,
                "auto_execution_enabled": False,
            },
        })

        self.assertEqual(control["status"], "CONFIGURED")
        self.assertTrue(control["forward_enabled"])
        self.assertEqual(control["live_account_id"], "live_001")
        self.assertFalse(control["auto_execution_enabled"])

    def test_persisted_control_wins_over_legacy_config(self):
        restored = normalize_live_pilot_control(
            {
                "status": "STOPPED",
                "live_account_id": "live_002",
                "auto_execution_enabled": False,
                "execution_epoch": "pilot-002",
            },
            {"trend_forward": {"live_account_id": "legacy_001"}},
        )

        self.assertEqual(restored["status"], "STOPPED")
        self.assertEqual(restored["live_account_id"], "live_002")
        self.assertEqual(restored["execution_epoch"], "pilot-002")

    def test_preflight_requires_every_check(self):
        passed = project_preflight([
            {"code": "A", "ok": True, "message": "a"},
            {"code": "B", "ok": True, "message": "b"},
        ])
        failed = project_preflight([
            {"code": "A", "ok": True, "message": "a"},
            {"code": "B", "ok": False, "message": "b"},
        ])

        self.assertTrue(passed["passed"])
        self.assertFalse(failed["passed"])

    def test_epoch_is_strict_and_bounded(self):
        self.assertEqual(validate_epoch("live-small-2026-07-31-v1"), "live-small-2026-07-31-v1")
        with self.assertRaises(ValueError):
            validate_epoch("LIVE SMALL")


if __name__ == "__main__":
    unittest.main()
