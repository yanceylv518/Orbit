from __future__ import annotations

import sys
from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.r0_direction_sequence_diagnostics import (
    annotate_same_direction_sequence,
    create_direction_sequence_report,
    summarize_direction_sequence_slices,
)


class R0DirectionSequenceDiagnosticTests(unittest.TestCase):
    def test_sequence_increments_through_inclusive_24_hour_boundary(self):
        rows = annotate_same_direction_sequence([
            self._event("BTCUSDT", "LONG", 0),
            self._event("BTCUSDT", "LONG", 96),
            self._event("BTCUSDT", "LONG", 97),
        ])

        self.assertEqual([item["same_direction_sequence_number"] for item in rows], [1, 2, 3])

    def test_gap_over_24_hours_resets(self):
        rows = annotate_same_direction_sequence([
            self._event("BTCUSDT", "SHORT", 0),
            self._event("BTCUSDT", "SHORT", 97),
        ])

        self.assertEqual([item["same_direction_sequence_bucket"] for item in rows], ["SEQ_1", "SEQ_1"])

    def test_opposite_direction_resets_immediately(self):
        rows = annotate_same_direction_sequence([
            self._event("BTCUSDT", "LONG", 0),
            self._event("BTCUSDT", "LONG", 1),
            self._event("BTCUSDT", "SHORT", 2),
            self._event("BTCUSDT", "SHORT", 3),
        ])

        self.assertEqual([item["same_direction_sequence_number"] for item in rows], [1, 2, 1, 2])

    def test_symbols_are_independent_at_the_same_timestamp(self):
        rows = annotate_same_direction_sequence([
            self._event("BTCUSDT", "LONG", 0), self._event("ETHUSDT", "LONG", 0),
            self._event("BTCUSDT", "LONG", 1), self._event("ETHUSDT", "LONG", 1),
        ])

        by_symbol = {symbol: [row["same_direction_sequence_number"] for row in rows if row["symbol"] == symbol] for symbol in ("BTCUSDT", "ETHUSDT")}
        self.assertEqual(by_symbol, {"BTCUSDT": [1, 2], "ETHUSDT": [1, 2]})

    def test_earlier_labels_do_not_change_when_future_events_are_added(self):
        past = [self._event("BTCUSDT", "LONG", 0), self._event("BTCUSDT", "LONG", 1)]

        before = annotate_same_direction_sequence(past)
        after = annotate_same_direction_sequence(past + [self._event("BTCUSDT", "SHORT", 2)])

        self.assertEqual(
            [item["same_direction_sequence_number"] for item in before],
            [item["same_direction_sequence_number"] for item in after[:2]],
        )

    def test_cross_slice_contains_every_direction_and_bucket(self):
        rows = annotate_same_direction_sequence([
            self._event("BTCUSDT", "LONG", 0), self._event("BTCUSDT", "SHORT", 1),
        ])

        result = summarize_direction_sequence_slices(rows, bootstrap_samples=10, bootstrap_seed=7)

        self.assertEqual(set(result["by_direction"]), {"LONG", "SHORT"})
        self.assertEqual(set(result["by_same_direction_sequence"]), {"SEQ_1", "SEQ_2", "SEQ_3", "SEQ_4_PLUS"})
        self.assertEqual(set(result["direction_by_same_direction_sequence"]["SHORT"]), {"SEQ_1", "SEQ_2", "SEQ_3", "SEQ_4_PLUS"})

    def test_oversold_short_is_rejected(self):
        baseline = {
            "verdict": "TRAINING_FAIL",
            "parameter_reports": [{
                "parameter_id": "p1", "family_id": "OVERSOLD_REBOUND",
                "definition_id": "S1_DROP_STABILIZATION", "parameters": {},
                "summary": {"event_count": 1, "mean_net_return_pct": 1.0},
            }],
        }
        context = {"contract_sha256": "c", "manifest": {"dataset_fingerprint": "d"}}

        with self.assertRaisesRegex(ValueError, "forbidden SHORT"):
            create_direction_sequence_report(
                context, baseline, {"p1": [self._event("BTCUSDT", "SHORT", 0)]},
                baseline_report_sha256="b", bootstrap_samples=10, bootstrap_seed=7,
            )

    def test_every_parameter_and_definition_contains_all_required_slices(self):
        parameter_reports = []
        events = {}
        for index, family in enumerate(("BREAKOUT_MOMENTUM", "OVERSOLD_REBOUND"), 1):
            parameter_id = f"p{index}"
            direction = "LONG" if family == "OVERSOLD_REBOUND" else "SHORT"
            parameter_reports.append({
                "parameter_id": parameter_id, "family_id": family,
                "definition_id": "S1_DROP_STABILIZATION" if family == "OVERSOLD_REBOUND" else "B1_DONCHIAN_VOLUME",
                "parameters": {"holding_candles": index},
                "summary": {"event_count": 1, "mean_net_return_pct": 1.0},
            })
            events[parameter_id] = [self._event("BTCUSDT", direction, index)]
        report = create_direction_sequence_report(
            {"contract_sha256": "c", "manifest": {"dataset_fingerprint": "d"}},
            {"verdict": "TRAINING_FAIL", "parameter_reports": parameter_reports},
            events, baseline_report_sha256="b", bootstrap_samples=10, bootstrap_seed=7,
        )

        required = {
            "overall", "by_direction", "by_same_direction_sequence",
            "direction_by_same_direction_sequence",
        }
        self.assertEqual(len(report["parameter_reports"]), 2)
        for item in report["parameter_reports"]:
            self.assertEqual(set(item["slices"]), required)
            self.assertEqual(set(item["slices"]["by_direction"]), {"LONG", "SHORT"})
            self.assertEqual(
                set(item["slices"]["direction_by_same_direction_sequence"]["SHORT"]),
                {"SEQ_1", "SEQ_2", "SEQ_3", "SEQ_4_PLUS"},
            )
        self.assertEqual(
            set(report["definition_reports"]),
            {"B1_DONCHIAN_VOLUME", "S1_DROP_STABILIZATION"},
        )
        for item in report["definition_reports"].values():
            self.assertEqual(set(item["slices"]), required)

    @staticmethod
    def _event(symbol, direction, candle):
        return {
            "symbol": symbol, "direction": direction,
            "signal_time_ms": candle * 15 * 60 * 1000,
            "entry_day_utc": f"2026-01-{1 + candle // 96:02d}",
            "net_return_pct": 1.0,
        }


if __name__ == "__main__":
    unittest.main()
