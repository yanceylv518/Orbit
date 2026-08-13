from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orbit.application.rb1_oversold import RB1Error, create_step1_report, create_step2_report
from orbit.domain.calibration.r0_shortline import ShortlineCandle, simulate_symbol_events
from orbit.domain.calibration.rb1_oversold import detect_signals, frozen_candidates, simulate_candidate_events

MS = 900_000


def candles(values, *, lows=None, highs=None, opens=None):
    opens = opens or values
    lows = lows or [min(o, c) - 1 for o, c in zip(opens, values)]
    highs = highs or [max(o, c) + 1 for o, c in zip(opens, values)]
    return [ShortlineCandle(i * MS, (i + 1) * MS - 1, float(o), float(h), float(l), float(c), 1_000_000) for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, values))]


class RB1Tests(unittest.TestCase):
    def test_grid_is_exactly_four_and_rejects_extra(self):
        contract = {"candidates": [{"id": item} for item in ("ST-A__EX-A", "ST-A__EX-B", "ST-B__EX-A", "ST-B__EX-B")], "discipline": {"grid_size_max": 4}}
        self.assertEqual(len(frozen_candidates(contract)), 4)
        contract["candidates"].append({"id": "EXTRA"})
        with self.assertRaises(ValueError): frozen_candidates(contract)

    def test_same_signal_engine_as_r0_only_exit_differs(self):
        values = [100] * 17 + [88, 89] + [89] * 40
        rows = candles(values, opens=[100] * 17 + [89, 88] + [89] * 40)
        indices = detect_signals(rows, start_ms=0, end_ms=10**12)
        r0 = simulate_symbol_events("X", rows, [], "S1_DROP_STABILIZATION", {"return_lookback_candles": 16, "minimum_drop_fraction": ".10", "holding_candles": 32}, tier_at=lambda *_: "HIGH", evaluation_start_ms=0, evaluation_end_ms=10**12, round_trip_cost_pct_by_tier={"HIGH": .16})
        self.assertEqual([rows[i].close_time_ms for i in indices], [item["signal_time_ms"] for item in r0])

    def test_st_b_uses_signal_candle_low_and_r_is_entry_minus_stop(self):
        values = [100] * 17 + [88, 89] + [89] * 40
        rows = candles(values, opens=[100] * 17 + [89, 88] + [89] * 40)
        signal = detect_signals(rows, start_ms=0, end_ms=10**12)
        event = simulate_candidate_events("X", rows, [], signal, "ST-B__EX-A", tier_at=lambda *_: "HIGH", costs={"HIGH": 0}, end_ms=10**12)[0]
        self.assertAlmostEqual(event["initial_stop_price"], rows[signal[0]].low - .5 * event["atr14"])
        self.assertAlmostEqual(event["initial_r"], event["entry_price"] - event["initial_stop_price"])

    def test_ex_a_trigger_and_trailing_only_moves_up_next_candle(self):
        values = [100] * 17 + [88, 89] + [89, 96, 94, 93] + [93] * 36
        rows = candles(values, opens=[100] * 17 + [89, 88] + [89, 89, 96, 94, 93] + [93] * 35, lows=[99] * 17 + [87, 88] + [88, 95, 93, 92] + [92] * 36, highs=[101] * 17 + [90, 90] + [90, 97, 95, 94] + [94] * 36)
        signal = detect_signals(rows, start_ms=0, end_ms=10**12)
        event = simulate_candidate_events("X", rows, [], signal, "ST-A__EX-A", tier_at=lambda *_: "HIGH", costs={"HIGH": 0}, end_ms=10**12)[0]
        history = event["trailing_stop_history"]
        self.assertTrue(all(a["stop_price"] <= b["stop_price"] for a, b in zip(history, history[1:])))
        self.assertTrue(all(item["effective_from_index"] > signal[0] + 1 for item in history[1:]))

    def test_ex_b_half_close_composes_weighted_return_and_1_5r(self):
        values = [100] * 17 + [88, 89] + [89, 100] + [100] * 39
        rows = candles(values, opens=[100] * 17 + [89, 88] + [89] * 41, lows=[99] * 17 + [87, 88] + [88] * 41, highs=[101] * 17 + [90, 90] + [90, 105] + [101] * 39)
        signal = detect_signals(rows, start_ms=0, end_ms=10**12)
        event = simulate_candidate_events("X", rows, [], signal, "ST-B__EX-B", tier_at=lambda *_: "HIGH", costs={"HIGH": 0}, end_ms=10**12)[0]
        self.assertEqual(event["legs"][0]["weight"], .5)
        expected = sum(leg["weight"] * (leg["exit_price"] / event["entry_price"] - 1) for leg in event["legs"]) * 100
        self.assertAlmostEqual(event["price_return_pct"], expected)

    def test_gap_executes_worse_and_stop_precedes_time_exit(self):
        values = [100] * 17 + [88, 89] + [89] * 32 + [80]
        opens = [100] * 17 + [89, 88] + [89] * 32 + [80]
        rows = candles(values, opens=opens, lows=[99] * 17 + [87, 88] + [88] * 32 + [79])
        signal = detect_signals(rows, start_ms=0, end_ms=10**12)
        event = simulate_candidate_events("X", rows, [], signal, "ST-B__EX-A", tier_at=lambda *_: "HIGH", costs={"HIGH": 0}, end_ms=10**12)[0]
        self.assertEqual(event["exit_reason"], "STOP_GAP")
        self.assertEqual(event["legs"][-1]["exit_price"], 80)

    def test_step12_never_call_lockbox_loader_and_step2_uses_winner_only(self):
        values = [100] * 17 + [88, 89] + [89] * 40
        rows = candles(values, opens=[100] * 17 + [89, 88] + [89] * 40)
        contract = json.loads((Path(__file__).parents[2] / "config/research/rb1_oversold.v1.json").read_text())
        context = {"contract": contract, "contract_sha256": "x", "manifest": {"dataset_fingerprint": "d"}}
        with tempfile.TemporaryDirectory(dir=Path(__file__).parents[2] / "var") as temp:
            checkpoints = Path(temp) / "cp"
            report = create_step1_report(context, ["X"], lambda _: (rows, []), tier_at=lambda *_: "HIGH", checkpoint_dir=checkpoints)
            step2 = create_step2_report(context, report, checkpoints)
            self.assertFalse(report["lockbox_data_read"])
            self.assertFalse(step2["lockbox_data_read"])
            self.assertEqual(step2["step1_winner"], report["winner"])


if __name__ == "__main__": unittest.main()
