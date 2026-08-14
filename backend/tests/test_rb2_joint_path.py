from __future__ import annotations

import unittest
import hashlib
import json
from pathlib import Path

from orbit.application.rb2_joint_path import MFE_BUCKETS, joint_bucket_summary, mfe_bucket


class RB2JointPathTests(unittest.TestCase):
    def test_mfe_bucket_boundaries_are_unambiguous(self):
        self.assertEqual(mfe_bucket(1.999), "LT_2R")
        self.assertEqual(mfe_bucket(2), "GTE_2_LT_5R")
        self.assertEqual(mfe_bucket(5), "GTE_5_LT_10R")
        self.assertEqual(mfe_bucket(10), "GTE_10R")

    def test_joint_summary_keeps_timing_and_price_conversion(self):
        rows = [
            {
                "mfe_r": 12,
                "mae_r": 1,
                "mae_entry_price_pct": 2,
                "mfe_bar": 8,
                "mae_bar": 2,
                **{f"early_mae_{window}_r": window / 10 for window in (4, 8, 16, 32)},
                **{f"early_mae_{window}_entry_price_pct": window / 5 for window in (4, 8, 16, 32)},
            },
            {
                "mfe_r": 15,
                "mae_r": 3,
                "mae_entry_price_pct": 6,
                "mfe_bar": 4,
                "mae_bar": 9,
                **{f"early_mae_{window}_r": window / 20 for window in (4, 8, 16, 32)},
                **{f"early_mae_{window}_entry_price_pct": window / 10 for window in (4, 8, 16, 32)},
            },
        ]
        result = joint_bucket_summary(rows)
        self.assertEqual(result["event_count"], 2)
        self.assertEqual(result["mae_r"]["quantiles"]["p50"], 2)
        self.assertEqual(result["mae_entry_price_pct"]["quantiles"]["p50"], 4)
        self.assertEqual(result["mae_vs_mfe_timing"]["rates"]["BEFORE_MFE"], 0.5)
        self.assertEqual(result["mae_vs_mfe_timing"]["rates"]["AFTER_MFE"], 0.5)
        self.assertIn("32", result["early_mae"])

    def test_contract_is_training_only_and_binds_source_report(self):
        root = Path(__file__).parents[2]
        contract = json.loads((root / "config/research/rb2_joint_path.v1.json").read_text(encoding="utf-8"))
        source = root / "docs/evidence/rb2/rb2_long_cycle_v3_20260814.json"
        self.assertLess(contract["training_end_ms"], contract["lockbox_start_ms"])
        self.assertEqual(contract["discipline"]["lockbox_access"], "PROHIBITED")
        self.assertEqual(contract["source_report_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_runner_exposes_no_lockbox_command(self):
        source = (Path(__file__).parents[1] / "tools/run_rb2_joint_path.py").read_text(encoding="utf-8")
        self.assertNotIn("lockbox_end_ms", source)
        self.assertNotIn("confirm-open-lockbox", source)
        self.assertIn("maximum_time_ms=training_end_ms", source)

    def test_formal_report_is_complete_and_non_decisive(self):
        root = Path(__file__).parents[2]
        report = json.loads(
            (root / "docs/evidence/rb2/rb2_joint_path_v4_20260814.json").read_text(encoding="utf-8")
        )
        self.assertEqual(report["event_count_total"], 1_637_351)
        self.assertEqual(report["symbol_count"], 387)
        self.assertFalse(report["lockbox_opened"])
        self.assertFalse(report["lockbox_data_read"])
        self.assertEqual(len(report["family_reports"]), 2)
        self.assertEqual(len(report["parameter_reports"]), 12)
        for scope in report["family_reports"] + report["parameter_reports"]:
            self.assertEqual(set(scope["horizons"]), {"96", "288", "960"})
            for horizon in scope["horizons"].values():
                self.assertEqual(set(horizon), set(MFE_BUCKETS))
                for bucket in horizon.values():
                    self.assertEqual(set(bucket["early_mae"]), {"4", "8", "16", "32"})
        lowered = str(report).lower()
        for forbidden in ("verdict", "passed", "failed", "threshold"):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
