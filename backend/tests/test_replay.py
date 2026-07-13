import math
import sys
import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.calibration.history import FundingPoint, MarketCandle
from orbit.domain.calibration.replay import (
    aggregate_replay_markets,
    compare_replay_variants,
    replay_event_engine,
    replay_walk_forward,
    replay_walk_forward_tuned_loss_reduction,
    strategy_variant,
)
from orbit.domain.strategy.engine import EventEngine


def strategy():
    return load_config(str(ROOT / "config" / "config.sample.json"))["strategy_instances"][0]


class EventEngineReplayTest(unittest.TestCase):
    def test_intrabar_price_does_not_advance_close_only_state(self):
        engine = EventEngine(strategy())
        state = engine.initialize_symbol("BTCUSDT", Decimal("100"), Decimal("100"))

        intrabar, _, _ = engine.on_intrabar_price(state, Decimal("105"))

        self.assertEqual(intrabar["tick_count"], 0)
        self.assertEqual(len(intrabar["regime_price_history"]), 1)
        self.assertEqual(intrabar["trend_entry_candidate_count"], 0)
        closed, _, _ = engine.on_tick(intrabar, Decimal("102"))
        self.assertEqual(closed["tick_count"], 1)
        self.assertEqual(len(closed["regime_price_history"]), 2)

    def test_flat_market_has_no_strategy_trades_but_charges_initial_entry(self):
        report = replay_event_engine([100.0] * 100, strategy(), close_out=False)

        self.assertEqual(report["trade_count"], 0)
        self.assertEqual(report["initial_entry_trade_count"], 2)
        self.assertLess(report["net_pnl_usdt"], 0.0)
        self.assertEqual(report["accounting_identity_error_usdt"], 0.0)

    def test_terminal_closeout_charges_fees_and_slippage(self):
        report = replay_event_engine([100.0] * 100, strategy())

        self.assertEqual(report["trade_count"], 0)
        self.assertEqual(report["terminal_closeout_trade_count"], 2)
        self.assertLess(report["net_pnl_usdt"], 0.0)
        self.assertGreater(report["fee_total_usdt"], 0.0)
        self.assertGreater(report["slippage_total_usdt"], 0.0)

    def test_oscillating_market_reuses_engine_and_harvests(self):
        closes = [
            100 * (1 + 0.025 * math.sin(2 * math.pi * index / 24))
            for index in range(24 * 8 + 1)
        ]
        configured = deepcopy(strategy())
        configured["strategy"]["regime_gate"].update({
            "confirm_ticks": 1,
            "range_max_autocorrelation": 1.0,
        })
        report = replay_event_engine(closes, configured)

        self.assertGreater(report["trade_count"], 0)
        self.assertGreater(report["net_pnl_usdt"], 0)
        self.assertTrue(any(name.startswith("PROFIT_TRANSFER") for name in report["event_counts"]))
        self.assertAlmostEqual(report["accounting_identity_error_usdt"], 0.0, places=6)
        self.assertEqual(report["final_long_qty"], 0.0)
        self.assertEqual(report["final_short_qty"], 0.0)
        self.assertEqual(report["terminal_closeout_trade_count"], 2)

    def test_replay_rejects_insufficient_prices(self):
        with self.assertRaises(ValueError):
            replay_event_engine([100.0], strategy())

    def test_walk_forward_replay_uses_independent_validation_folds(self):
        prices = [100 + math.sin(index / 3) for index in range(240)]
        result = replay_walk_forward(
            prices,
            strategy(),
            symbol="BTCUSDT",
            train_size=100,
            validation_size=40,
            step=40,
        )

        self.assertEqual(len(result["folds"]), 3)
        self.assertEqual(result["folds"][0]["validation_start"], 100)
        self.assertEqual(result["folds"][1]["validation_start"], 140)
        self.assertTrue(all(fold["report"]["terminal_closeout_enabled"] for fold in result["folds"]))

    def test_historical_funding_changes_realized_equity_and_reconciles(self):
        configured = strategy()
        configured["strategy"]["regime_gate"]["enabled"] = False
        closes = [100 + index * 0.5 for index in range(30)]
        times = [index * 3_600_000 for index in range(30)]
        funding = [FundingPoint(times[0], 0.001), FundingPoint(times[-1], 0.001)]

        report = replay_event_engine(
            closes,
            configured,
            candle_times_ms=times,
            funding_points=funding,
        )

        self.assertTrue(report["funding_coverage_complete"])
        self.assertEqual(report["funding_points_applied"], 2)
        self.assertNotEqual(report["funding_total_usdt"], 0.0)
        self.assertAlmostEqual(report["accounting_identity_error_usdt"], 0.0, places=6)

    def test_intrabar_replay_processes_one_close_tick_per_candle(self):
        candles = [
            MarketCandle(index, 100, 102, 98, 100)
            for index in range(20)
        ]
        report = replay_event_engine(
            [candle.close for candle in candles],
            strategy(),
            intrabar_candles=candles,
        )

        self.assertEqual(report["closed_candles_processed"], len(candles) - 1)
        self.assertEqual(sum(report["intrabar_path_counts"].values()), len(candles) - 1)
        self.assertEqual(report["intrabar_model"], "myopic_min_close_equity_of_OHLC_OLHC")

    def test_fixed_intrabar_paths_are_reported_explicitly(self):
        candles = [MarketCandle(index, 100, 103, 97, 101) for index in range(10)]
        closes = [candle.close for candle in candles]

        ohlc = replay_event_engine(closes, strategy(), intrabar_candles=candles, intrabar_mode="fixed_ohlc")
        olhc = replay_event_engine(closes, strategy(), intrabar_candles=candles, intrabar_mode="fixed_olhc")

        self.assertEqual(ohlc["intrabar_model"], "fixed_O_H_L_C")
        self.assertEqual(ohlc["intrabar_path_counts"], {"O-H-L-C": 9})
        self.assertEqual(olhc["intrabar_model"], "fixed_O_L_H_C")
        self.assertEqual(olhc["intrabar_path_counts"], {"O-L-H-C": 9})

    def test_variant_comparison_propagates_funding_and_intrabar_mode(self):
        candles = [MarketCandle(index * 3_600_000, 100, 102, 98, 100) for index in range(30)]
        funding = [FundingPoint(candles[0].close_time_ms, 0.001)]
        result = compare_replay_variants(
            [candle.close for candle in candles],
            strategy(),
            symbol="BTCUSDT",
            train_size=10,
            validation_size=10,
            candle_times_ms=[candle.close_time_ms for candle in candles],
            funding_points=funding,
            intrabar_candles=candles,
            intrabar_mode="fixed_ohlc",
            variants=["full", "neutral_hold"],
        )

        self.assertEqual(set(result), {"full", "neutral_hold"})
        for variant in result.values():
            self.assertTrue(all(
                fold["report"]["intrabar_model"] == "fixed_O_H_L_C"
                for fold in variant["folds"]
            ))

    def test_market_stage_gate_blocks_when_funding_is_unavailable(self):
        prices = [100 + math.sin(index / 3) for index in range(240)]
        result = replay_walk_forward(
            prices,
            strategy(),
            symbol="BTCUSDT",
            train_size=100,
            validation_size=40,
            step=40,
        )
        summary = aggregate_replay_markets([{"name": "BTC", "result": result}])

        self.assertFalse(summary["funding_complete"])
        self.assertEqual(summary["funding_points_applied"], 0)
        self.assertFalse(summary["stage_admitted"])
        self.assertIsInstance(summary["event_attribution"], dict)

    def test_neutral_hold_variant_disables_all_strategy_events(self):
        configured = strategy_variant(strategy(), "neutral_hold")
        closes = [100 * (1 + 0.03 * math.sin(2 * math.pi * index / 24)) for index in range(200)]
        report = replay_event_engine(closes, configured)

        self.assertEqual(report["event_count"], 0)
        self.assertEqual(report["trade_count"], 0)

    def test_profit_transfer_reduce_only_disables_loss_side_averaging(self):
        configured = strategy_variant(strategy(), "profit_transfer_reduce_only")

        self.assertEqual(
            configured["strategy"]["events"]["profit_transfer"]["sizing"]
            ["use_realized_profit_ratio_for_loss_side"],
            0,
        )
        self.assertEqual(
            strategy()["strategy"]["events"]["profit_transfer"]["sizing"]
            ["use_realized_profit_ratio_for_loss_side"],
            0.8,
        )

    def test_profit_transfer_only_disables_trend_reduction_and_recovery(self):
        configured = strategy_variant(strategy(), "profit_transfer_only")
        events = configured["strategy"]["events"]

        self.assertTrue(events["profit_transfer"]["enabled"])
        self.assertFalse(events["loss_side_reduction"]["enabled"])
        self.assertFalse(events["position_recovery"]["enabled"])

    def test_event_attribution_reconciles_event_totals(self):
        configured = strategy_variant(strategy(), "full")
        configured["strategy"]["regime_gate"].update({"confirm_ticks": 1, "range_max_autocorrelation": 1.0})
        closes = [100 * (1 + 0.025 * math.sin(2 * math.pi * index / 24)) for index in range(200)]
        report = replay_event_engine(closes, configured)

        self.assertEqual(
            sum(item["events"] for item in report["event_attribution"].values()),
            report["event_count"],
        )
        self.assertEqual(
            sum(item["trades"] for item in report["event_attribution"].values()),
            report["trade_count"],
        )

    def test_tuned_loss_reduction_does_not_read_validation_prices(self):
        closes = [100 * (1 + 0.02 * math.sin(index / 5)) for index in range(180)]
        altered = list(closes)
        altered[100:140] = [100 + index for index in range(40)]
        kwargs = {
            "strategy_config": strategy(),
            "symbol": "BTCUSDT",
            "train_size": 100,
            "validation_size": 40,
            "step": 40,
        }

        original = replay_walk_forward_tuned_loss_reduction(closes, **kwargs)
        changed = replay_walk_forward_tuned_loss_reduction(altered, **kwargs)

        self.assertEqual(
            original["folds"][0]["selected_candidate"],
            changed["folds"][0]["selected_candidate"],
        )
        self.assertEqual(
            original["folds"][0]["training_report"],
            changed["folds"][0]["training_report"],
        )


if __name__ == "__main__":
    unittest.main()
