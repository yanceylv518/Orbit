from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.r0_path_diagnostics import assert_training_reproduced, summarize_path_answers
from orbit.application.r0_shortline_screen import validate_training_report, verify_frozen_context


class R0PathDiagnosticTests(unittest.TestCase):
    def test_reproduction_gate_requires_every_training_field_to_match(self):
        baseline = {"verdict": "TRAINING_FAIL", "parameter_reports": [{"value": 1.0}]}
        assert_training_reproduced(baseline, json.loads(json.dumps(baseline)))
        changed = json.loads(json.dumps(baseline))
        changed["parameter_reports"][0]["value"] = 1.000001

        with self.assertRaisesRegex(ValueError, "differs"):
            assert_training_reproduced(baseline, changed)

    def test_committed_baseline_remains_the_exact_frozen_training_failure(self):
        context = verify_frozen_context(
            ROOT / "config" / "research" / "r0_shortline_screen.v2.json",
            ROOT / "var" / "calibration" / "shortline-data-v1",
        )
        path = ROOT / "docs" / "evidence" / "r0" / "r0_training_v2_20260812.json"
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        report = json.loads(raw.decode("utf-8"))

        validate_training_report(context, report)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "8d5c9681a7877777bcfc93725e7220ba32c747a7d6a536c97fa837c11c4cfec6")
        self.assertEqual(report["verdict"], "TRAINING_FAIL")
        self.assertEqual(report["lockbox_authorized_families"], [])
        self.assertEqual(len(report["parameter_reports"]), 16)

    def test_five_required_answers_are_structured_and_year_sliced(self):
        events = [
            self._event(2022, 1.0, 2.5, 1.2, 4, stopped=True, later=True),
            self._event(2023, -1.0, 0.8, 2.3, 8, stopped=False, later=False),
        ]

        answers = summarize_path_answers(events)

        self.assertEqual(set(answers), {
            "mfe_vs_actual_return", "mae_before_profitable_exit", "mfe_arrival",
            "stop_then_new_high", "by_year",
        })
        self.assertEqual(set(answers["by_year"]), {"2022", "2023"})
        self.assertEqual(answers["stop_then_new_high"]["share_of_stops_2h"], 1.0)

    @staticmethod
    def _event(year, net, mfe, mae, bar, *, stopped, later):
        path = {
            "mfe_pct": mfe, "mae_pct": mae, "mfe_atr": mfe / 2,
            "mae_atr": mae / 2, "mfe_bar": bar, "mae_bar": 2,
        }
        return {
            "entry_year_utc": year,
            "net_return_pct": net,
            "path_diagnostics": {
                "executed": path,
                "holding_h": path,
                "holding_2h": path,
                "stopped": stopped,
                "stop_then_new_mfe_h": later,
                "stop_then_new_mfe_2h": later,
            },
        }


if __name__ == "__main__":
    unittest.main()
