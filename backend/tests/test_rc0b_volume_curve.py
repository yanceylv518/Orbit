from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from orbit.application.rc0b_volume_curve import (
    breakout_shape,
    distribution_summary,
    frequency_summary,
    large_opportunity_retention,
    select_combination,
)
from orbit.domain.calibration.r0_shortline import ShortlineCandle


DAY_MS = 86_400_000


def candles(count: int):
    return [
        ShortlineCandle(
            open_time_ms=index * 900_000,
            close_time_ms=(index + 1) * 900_000 - 1,
            open=100 + index,
            high=101.5 + index,
            low=99.5 + index,
            close=101 + index,
            quote_volume=1000 if index < count - 1 else 4000,
        )
        for index in range(count)
    ]


class RC0BVolumeCurveTests(unittest.TestCase):
    def test_breakout_shape_uses_prior_candles_and_is_direction_symmetric(self):
        rows = candles(301)
        result = breakout_shape(rows, 300, "LONG")
        self.assertAlmostEqual(result["relative_quote_volume"], 4.0)
        self.assertTrue(all(result["breaks_channel"].values()))
        self.assertFalse(breakout_shape(rows, 100, "SHORT")["breaks_channel"]["288"])

    def test_combination_selection_is_nested_by_liquidity_and_shape(self):
        events = [
            {
                "signal_time_ms": DAY_MS,
                "eligible_30000000": 1,
                "eligible_200000000": 1,
                "breaks_channel_32": 1,
                "breaks_channel_96": 1,
                "relative_quote_volume": 3.0,
            },
            {
                "signal_time_ms": 2 * DAY_MS,
                "eligible_30000000": 1,
                "eligible_200000000": 0,
                "breaks_channel_32": 1,
                "breaks_channel_96": 0,
                "relative_quote_volume": 2.0,
            },
        ]
        broad = select_combination(
            events,
            liquidity_threshold_usdt=30_000_000,
            channel_lookback_candles=32,
            minimum_relative_quote_volume=1.5,
        )
        strict = select_combination(
            events,
            liquidity_threshold_usdt=200_000_000,
            channel_lookback_candles=96,
            minimum_relative_quote_volume=2.5,
        )
        self.assertEqual(len(broad), 2)
        self.assertEqual(len(strict), 1)

    def test_frequency_includes_zero_days_and_months(self):
        events = [
            {"signal_time_ms": DAY_MS},
            {"signal_time_ms": DAY_MS + 1},
            {"signal_time_ms": 32 * DAY_MS},
        ]
        summary = frequency_summary(events, start_day_ms=0, end_day_ms=58 * DAY_MS)
        self.assertEqual(summary["calendar_day_count"], 59)
        self.assertEqual(summary["calendar_month_count"], 2)
        self.assertAlmostEqual(summary["mean_signals_per_day"], 3 / 59)
        self.assertEqual(summary["maximum_signals_per_day"], 2)
        self.assertEqual(sum(summary["by_month"].values()), 3)

    def test_large_opportunity_retention_ignores_unlabeled_tail(self):
        source = [
            {"large_opportunity": 1},
            {"large_opportunity": 0},
            {"large_opportunity": None},
        ]
        result = large_opportunity_retention(source, source[:1])
        self.assertEqual(result["source_labeled_event_count"], 2)
        self.assertEqual(result["retained_large_opportunity_fraction"], 1)

    def test_distribution_has_requested_daily_percentiles(self):
        result = distribution_summary([0, 1, 2, 3, 100])
        self.assertEqual(result["minimum"], 0)
        self.assertEqual(result["p50"], 2)
        self.assertEqual(result["maximum"], 100)
        self.assertEqual(set(result), {"count", "mean", "minimum", "p10", "p25", "p50", "p75", "p90", "p99", "maximum"})

    def test_contract_is_count_only_training_data_and_binds_rc0(self):
        root = Path(__file__).parents[2]
        contract_path = root / "config/research/rc0b_volume_curve.v1.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        source = root / contract["source_rc0_report"]
        self.assertEqual(contract["source_rc0_report_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertLess(contract["training_end_ms"], contract["lockbox_start_ms"])
        self.assertTrue(contract["discipline"]["descriptive_counts_only"])
        self.assertFalse(contract["discipline"]["predictive_filter_added"])
        self.assertEqual(contract["discipline"]["lockbox_access"], "PROHIBITED")
        self.assertEqual(contract["liquidity"]["thresholds_usdt"], [30_000_000, 100_000_000, 200_000_000, 500_000_000])

    def test_runner_exposes_no_lockbox_or_selection_command(self):
        source = (Path(__file__).parents[1] / "tools/run_rc0b_volume_curve.py").read_text(encoding="utf-8")
        self.assertNotIn("lockbox_end_ms", source)
        self.assertNotIn("confirm-open-lockbox", source)
        self.assertNotIn("--select", source)
        self.assertIn("maximum_time_ms=int(spec[\"training_end_ms\"])", source)

    def test_formal_report_has_all_combinations_when_archived(self):
        root = Path(__file__).parents[2]
        path = root / "docs/evidence/rc0/rc0b_volume_curve_v1_20260814.json"
        if not path.exists():
            self.skipTest("formal RC-0B report not generated yet")
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(report["source_event_count"], 434_558)
        self.assertFalse(report["lockbox_opened"])
        self.assertFalse(report["lockbox_data_read"])
        self.assertFalse(report["predictive_filter_added"])
        families = {row["family_id"]: row for row in report["family_reports"]}
        self.assertEqual(len(families["BREAKOUT_MOMENTUM"]["combinations"]), 36)
        self.assertEqual(len(families["OVERSOLD_REBOUND"]["combinations"]), 4)
        breakout_base = next(
            row
            for row in families["BREAKOUT_MOMENTUM"]["combinations"]
            if row["liquidity_threshold_usdt"] == 30_000_000
            and row["channel_lookback_candles"] == 32
            and row["minimum_relative_quote_volume"] == 1.5
        )
        oversold_base = next(
            row
            for row in families["OVERSOLD_REBOUND"]["combinations"]
            if row["liquidity_threshold_usdt"] == 30_000_000
        )
        self.assertEqual(breakout_base["frequency"]["event_count"], 406_245)
        self.assertEqual(oversold_base["frequency"]["event_count"], 28_313)
        for family in families.values():
            for combination in family["combinations"]:
                frequency = combination["frequency"]
                self.assertEqual(sum(frequency["by_month"].values()), frequency["event_count"])
                self.assertEqual(
                    frequency["daily_signal_count_distribution"]["count"],
                    frequency["calendar_day_count"],
                )
                self.assertAlmostEqual(
                    frequency["mean_signals_per_day"],
                    frequency["event_count"] / frequency["calendar_day_count"],
                )


if __name__ == "__main__":
    unittest.main()
