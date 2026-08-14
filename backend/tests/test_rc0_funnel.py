from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from orbit.application.rc0_funnel import funnel_curve, signal_features
from orbit.domain.calibration.r0_shortline import ShortlineCandle


MS = 900_000


def candles(count: int):
    return [
        ShortlineCandle(
            open_time_ms=index * MS,
            close_time_ms=(index + 1) * MS - 1,
            open=100 + index,
            high=101.2 + index,
            low=99.8 + index,
            close=101 + index,
            quote_volume=1_000,
        )
        for index in range(count)
    ]


class RC0FunnelTests(unittest.TestCase):
    def test_features_use_only_completed_history_and_align_direction(self):
        rows = candles(12)
        long_features = signal_features(rows, 10, "LONG", atr14=2, window=4)
        short_features = signal_features(rows, 10, "SHORT", atr14=2, window=4)
        self.assertEqual(long_features["efficiency_ratio"], 1)
        self.assertEqual(long_features["trend_strength"], 2)
        self.assertEqual(short_features["trend_strength"], -2)
        self.assertGreater(long_features["wickiness"], 0)
        self.assertIsNone(signal_features(rows, 3, "LONG", atr14=2, window=4))

    def test_funnel_reports_recall_precision_enrichment_and_monthly_load(self):
        month = 31 * 86_400_000
        events = []
        for index in range(12):
            events.append(
                {
                    "family_id": "BREAKOUT_MOMENTUM",
                    "symbol": f"S{index}",
                    "signal_time_ms": (index // 6) * month + (index % 6 + 1) * 86_400_000,
                    "direction": "LONG",
                    "efficiency_ratio": index,
                    "trend_strength": index,
                    "wickiness": 12 - index,
                    "large_opportunity": index >= 10,
                }
            )
        result = funnel_curve(events, "EFFICIENCY_RATIO", [0.5], workload_minimum=2, workload_maximum=4)
        point = result["curve"][0]
        self.assertEqual(point["actual_retained_event_count"], 6)
        self.assertEqual(point["large_opportunity_recall"], 1)
        self.assertAlmostEqual(point["large_opportunity_precision"], 2 / 6)
        self.assertAlmostEqual(point["enrichment"], 2)
        self.assertEqual(point["monthly_remaining_signals"]["mean"], 3)
        self.assertEqual(len(result["usable_workload_band"]["matching_points"]), 1)

    def test_combined_requires_all_three_marginal_selections(self):
        events = [
            {
                "family_id": "F",
                "symbol": f"S{index}",
                "signal_time_ms": (index + 1) * 86_400_000,
                "direction": "LONG",
                "efficiency_ratio": index,
                "trend_strength": index,
                "wickiness": 10 - index,
                "large_opportunity": index == 9,
            }
            for index in range(10)
        ]
        point = funnel_curve(events, "COMBINED", [0.2])["curve"][0]
        self.assertEqual(point["actual_retained_event_count"], 2)
        self.assertEqual(point["large_opportunity_recall"], 1)

    def test_contract_is_training_only_and_binds_joint_report(self):
        root = Path(__file__).parents[2]
        contract = json.loads((root / "config/research/rc0_funnel.v1.json").read_text(encoding="utf-8"))
        source = root / "docs/evidence/rb2/rb2_joint_path_v4_20260814.json"
        self.assertLess(contract["training_end_ms"], contract["lockbox_start_ms"])
        self.assertEqual(contract["discipline"]["lockbox_access"], "PROHIBITED")
        self.assertEqual(contract["source_joint_report_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_runner_exposes_no_lockbox_command(self):
        source = (Path(__file__).parents[1] / "tools/run_rc0_funnel.py").read_text(encoding="utf-8")
        self.assertNotIn("lockbox_end_ms", source)
        self.assertNotIn("confirm-open-lockbox", source)
        self.assertIn("maximum_time_ms=training_end_ms", source)

    def test_formal_report_has_complete_curves_and_no_decision(self):
        root = Path(__file__).parents[2]
        report = json.loads((root / "docs/evidence/rc0/rc0_funnel_v1_20260814.json").read_text(encoding="utf-8"))
        contract_path = root / "config/research/rc0_funnel.v1.json"
        source_path = root / "docs/evidence/rb2/rb2_joint_path_v4_20260814.json"
        self.assertEqual(report["contract_sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())
        self.assertEqual(report["source_joint_report_sha256"], hashlib.sha256(source_path.read_bytes()).hexdigest())
        self.assertEqual(report["deduplicated_event_count"], 434_558)
        self.assertFalse(report["lockbox_opened"])
        self.assertFalse(report["lockbox_data_read"])
        self.assertEqual(len(report["family_reports"]), 2)
        for family in report["family_reports"]:
            self.assertEqual(set(family["feature_windows"]), {"96", "288"})
            for feature_window in family["feature_windows"].values():
                self.assertEqual(set(feature_window["outcome_horizons"]), {"96", "288", "960"})
                for outcome in feature_window["outcome_horizons"].values():
                    self.assertEqual(set(outcome["filters"]), {"EFFICIENCY_RATIO", "TREND_STRENGTH", "WICKINESS", "COMBINED"})
                    for funnel in outcome["filters"].values():
                        self.assertEqual(len(funnel["curve"]), 9)
                        for point in funnel["curve"]:
                            self.assertEqual(
                                sum(point["monthly_remaining_signals"]["by_month"].values()),
                                point["actual_retained_event_count"],
                            )
        lowered = str(report).lower()
        for forbidden in ("verdict", "passed", "failed"):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
