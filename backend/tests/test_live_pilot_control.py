import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.live_pilot_control import (
    LIVE_PILOT_PROTOCOL,
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
        self.assertEqual(control["exposure_multiplier"], 3.0)
        self.assertEqual(control["initial_leverage"], 3)
        self.assertEqual(control["margin_type"], "ISOLATED")

    def test_legacy_config_cannot_authorize_v3_execution(self):
        control = default_live_pilot_control({
            "trend_forward": {
                "live_account_id": "live_001",
                "auto_execution_enabled": True,
                "auto_execution_epoch": "legacy-epoch",
            },
        })

        self.assertEqual(control["status"], "CONFIGURED")
        self.assertFalse(control["auto_execution_enabled"])
        self.assertEqual(control["execution_epoch"], "legacy-epoch")

    def test_persisted_control_wins_over_legacy_config(self):
        restored = normalize_live_pilot_control(
            {
                "protocol": LIVE_PILOT_PROTOCOL,
                "status": "STOPPED",
                "live_account_id": "live_002",
                "auto_execution_enabled": False,
                "execution_epoch": "pilot-002",
                "exposure_multiplier": 3,
                "initial_leverage": 3,
                "margin_type": "ISOLATED",
            },
            {"trend_forward": {"live_account_id": "legacy_001"}},
        )

        self.assertEqual(restored["status"], "STOPPED")
        self.assertEqual(restored["live_account_id"], "live_002")
        self.assertEqual(restored["execution_epoch"], "pilot-002")

    def test_legacy_live_authorization_is_invalidated_fail_closed(self):
        restored = normalize_live_pilot_control(
            {
                "protocol": "LIVE_SMALL_CONTROL_V1",
                "status": "ACTIVE",
                "live_account_id": "live_002",
                "auto_execution_enabled": True,
                "execution_epoch": "pilot-002",
            },
            {"trend_forward": {}},
        )

        self.assertEqual(restored["status"], "CONFIGURED")
        self.assertFalse(restored["auto_execution_enabled"])
        self.assertEqual(restored["execution_epoch"], "")
        self.assertIsNone(restored["last_preflight"])

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

    def test_preflight_allows_explicitly_deferred_signal_check(self):
        result = project_preflight([
            {"code": "ACCOUNT", "ok": True, "message": "account"},
            {
                "code": "CHECKLIST_READY",
                "ok": False,
                "required": False,
                "message": "waiting",
            },
        ])

        self.assertTrue(result["passed"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["deferred_count"], 1)

    def test_epoch_is_strict_and_bounded(self):
        self.assertEqual(validate_epoch("live-small-2026-07-31-v1"), "live-small-2026-07-31-v1")
        with self.assertRaises(ValueError):
            validate_epoch("LIVE SMALL")


if __name__ == "__main__":
    unittest.main()
