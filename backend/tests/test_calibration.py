import math
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (
    aggregate_reports,
    bootstrap_mean_interval,
    default_gate_config_grid,
    estimate,
    excursion_outcomes,
    expected_value_per_bet,
    extreme_funding_reaction_report,
    funding_relative_strength_report,
    gated_estimate,
    geometry_scan,
    funding_carry_screen,
    horizon_reversion_report,
    max_drawdown,
    normalize_funding_slots,
    pi_required,
    portfolio_calibration_summary,
    select_gate_config,
    walk_forward_compare,
    wilson_interval,
)
from orbit.domain.calibration.history import FundingPoint, MarketCandle


def sine_series(base=100.0, amplitude_pct=2.5, cycles=20, ticks_per_cycle=48):
    return [
        base * (1 + amplitude_pct / 100 * math.sin(2 * math.pi * i / ticks_per_cycle))
        for i in range(cycles * ticks_per_cycle)
    ]


def monotone_series(base=100.0, step_pct=0.2, ticks=400):
    return [base * (1 + step_pct / 100) ** i for i in range(ticks)]


class EstimatorTest(unittest.TestCase):
    def funding_points(self, rates, *, start=0, step=8 * 3_600_000):
        return [
            FundingPoint(start + index * step, rate)
            for index, rate in enumerate(rates)
        ]

    def candles(self, closes, *, start=0, step=1):
        return [
            MarketCandle(start + index * step, close, close, close, close)
            for index, close in enumerate(closes)
        ]

    def test_pi_required_matches_strategy_logic_formula(self):
        # STRATEGY_LOGIC §2：a=1.5, θ=4, c=0.14 → π_req = 1 − 1.36/4 = 0.66
        self.assertAlmostEqual(pi_required(1.5, 4.0, 0.14), 0.66, places=3)

    def test_expected_value_zero_at_required_pi(self):
        required = pi_required(1.5, 4.0, 0.14)
        self.assertAlmostEqual(expected_value_per_bet(required, 1.5, 4.0, 0.14), 0.0, places=9)

    def test_horizon_report_marks_reverting_series_profitable(self):
        report = horizon_reversion_report(
            sine_series(cycles=20), 1.5, 4.0, 0.14, max_holding_ticks=24,
        )

        self.assertGreater(report["reversions"], 10)
        self.assertGreater(report["expected_value_pct"], 0)
        self.assertEqual(report["extensions"], 0)

    def test_horizon_report_marks_monotone_extensions_unprofitable(self):
        report = horizon_reversion_report(
            monotone_series(ticks=400), 1.5, 4.0, 0.14, max_holding_ticks=24,
        )

        self.assertGreater(report["extensions"], 5)
        self.assertLess(report["expected_value_pct"], 0)

    def test_horizon_report_accounts_for_timeout_costs(self):
        report = horizon_reversion_report(
            [100, 102, 102.1, 102.2, 102.3],
            1.5,
            4.0,
            0.14,
            max_holding_ticks=2,
        )

        self.assertEqual(report["timeouts"], 1)
        self.assertAlmostEqual(
            report["gross_return_pct"] - report["cost_drag_pct"],
            report["net_return_pct"],
        )

    def test_funding_carry_screen_uses_non_overlapping_windows_and_costs(self):
        report = funding_carry_screen(
            self.funding_points([0.001] * 7),
            3,
            entry_exit_cost_pct=0.1,
            rebalance_cost_pct_per_day=0,
            bootstrap_samples=100,
        )

        self.assertEqual(report["events"], 2)
        self.assertEqual(report["discarded_points"], 1)
        self.assertAlmostEqual(report["mean_gross_funding_pct"], 0.3)
        self.assertAlmostEqual(report["mean_net_carry_pct"], 0.2)

    def test_funding_carry_screen_does_not_cross_data_gaps(self):
        first = self.funding_points([0.001] * 3)
        second = self.funding_points([0.001] * 3, start=first[-1].funding_time_ms + 24 * 3_600_000)
        report = funding_carry_screen(
            first + second,
            3,
            entry_exit_cost_pct=0,
            rebalance_cost_pct_per_day=0,
            bootstrap_samples=100,
        )

        self.assertEqual(report["contiguous_runs"], 2)
        self.assertEqual(report["events"], 2)

    def test_funding_carry_screen_requires_sample_and_positive_lower_bound(self):
        positive = funding_carry_screen(
            self.funding_points([0.001] * 90),
            3,
            entry_exit_cost_pct=0.1,
            rebalance_cost_pct_per_day=0,
            bootstrap_samples=200,
        )
        sparse = funding_carry_screen(
            self.funding_points([0.001] * 87),
            3,
            entry_exit_cost_pct=0.1,
            rebalance_cost_pct_per_day=0,
            bootstrap_samples=200,
        )

        self.assertTrue(positive["admitted"])
        self.assertGreater(positive["bootstrap_mean_ci_low"], 0)
        self.assertFalse(sparse["admitted"])

    def test_extreme_funding_reaction_uses_direction_and_cost(self):
        candles = self.candles([100.0, 100.0, 101.0, 102.0, 103.0])
        positive = extreme_funding_reaction_report(
            self.funding_points([0.001, 0.001, 0.001, 0.01], start=-30, step=10),
            candles,
            3,
            0.9,
            1,
            bootstrap_samples=20,
        )
        negative = extreme_funding_reaction_report(
            self.funding_points([-0.001, -0.001, -0.001, -0.01], start=-30, step=10),
            candles,
            3,
            0.9,
            1,
            bootstrap_samples=20,
        )

        self.assertEqual(positive["records"][0]["direction"], "short")
        self.assertEqual(negative["records"][0]["direction"], "long")
        self.assertLess(positive["mean_net_return_pct"], 0)
        self.assertGreater(negative["mean_net_return_pct"], 0)
        self.assertAlmostEqual(
            negative["records"][0]["net_return_pct"],
            negative["records"][0]["gross_return_pct"] - 0.14,
        )

    def test_extreme_funding_reaction_aligns_after_funding_close(self):
        report = extreme_funding_reaction_report(
            self.funding_points([0.001, 0.001, 0.001, 0.01], start=70, step=10),
            self.candles([100.0, 101.0, 103.0], start=100, step=10),
            3,
            0.9,
            1,
            cost_pct=0,
            bootstrap_samples=20,
        )

        self.assertEqual(report["records"][0]["funding_time_ms"], 100)
        self.assertEqual(report["records"][0]["entry_time_ms"], 110)
        self.assertEqual(report["records"][0]["exit_time_ms"], 120)

    def test_extreme_funding_reaction_excludes_current_rate_from_threshold(self):
        report = extreme_funding_reaction_report(
            self.funding_points([0.001] * 5 + [0.05], start=0, step=10),
            self.candles([100.0] * 70),
            5,
            0.95,
            1,
            bootstrap_samples=20,
        )

        self.assertAlmostEqual(report["records"][0]["threshold"], 0.001)

    def test_extreme_funding_reaction_does_not_read_future_funding(self):
        candles = self.candles([100.0 + index for index in range(100)])
        original = self.funding_points([0.001] * 5 + [-0.01, 0.001, 0.001], step=10)
        altered = self.funding_points([0.001] * 5 + [-0.01, 0.5, -0.5], step=10)

        first = extreme_funding_reaction_report(
            original, candles, 5, 0.95, 1, bootstrap_samples=20,
        )
        changed = extreme_funding_reaction_report(
            altered, candles, 5, 0.95, 1, bootstrap_samples=20,
        )

        self.assertEqual(first["records"][0], changed["records"][0])

    def test_extreme_funding_reaction_events_do_not_overlap(self):
        report = extreme_funding_reaction_report(
            self.funding_points([0.01] * 8, start=0, step=10),
            self.candles([100.0] * 100),
            2,
            0.9,
            15,
            bootstrap_samples=20,
        )

        records = report["records"]
        self.assertGreater(len(records), 1)
        for previous, current in zip(records, records[1:]):
            self.assertGreater(current["entry_time_ms"], previous["exit_time_ms"])

    def test_extreme_funding_reaction_admission_requires_robust_sample(self):
        prices = [100 * (1.002 ** index) for index in range(500)]
        report = extreme_funding_reaction_report(
            self.funding_points([-0.01] * 45, start=0, step=10),
            self.candles(prices),
            3,
            0.9,
            1,
            bootstrap_samples=200,
        )

        self.assertEqual(report["events"], 42)
        self.assertTrue(report["admitted"])
        self.assertGreater(report["bootstrap_mean_ci_low"], 0)

    def test_funding_slots_normalize_small_exchange_timestamp_offsets(self):
        slots = normalize_funding_slots(
            self.funding_points([0.01, 0.02, 0.03], start=1, step=4),
            settlement_interval_ms=10,
            tolerance_ms=2,
        )

        self.assertEqual(set(slots), {0, 10})
        self.assertAlmostEqual(slots[0].funding_rate, 0.01)
        self.assertAlmostEqual(slots[10].funding_rate, 0.03)

    def test_funding_strength_accounts_for_pair_direction_cashflows_and_cost(self):
        long_prices = [100.0] * 30
        long_prices[11] = 110.0
        markets = {
            "A": (
                self.funding_points([0.01, 0.02, 0.02], step=10),
                self.candles(long_prices),
            ),
            "B": (
                self.funding_points([-0.01, -0.02, -0.02], step=10),
                self.candles([100.0] * 30),
            ),
        }
        report = funding_relative_strength_report(
            markets,
            1,
            1,
            min_market_appearances=0,
            settlement_interval_ms=10,
            candle_interval_ms=1,
            bootstrap_samples=20,
        )
        event = report["records"][0]

        self.assertEqual(event["long_market"], "A")
        self.assertEqual(event["short_market"], "B")
        self.assertAlmostEqual(event["long_price_return_pct"], 10.0)
        self.assertAlmostEqual(event["long_funding_return_pct"], -2.0)
        self.assertAlmostEqual(event["short_funding_return_pct"], -2.0)
        self.assertAlmostEqual(event["gross_return_pct"], 3.0)
        self.assertAlmostEqual(event["net_return_pct"], 2.86)
        self.assertAlmostEqual(
            report["mean_price_return_pct"] + report["mean_funding_return_pct"],
            report["mean_gross_return_pct"],
        )
        self.assertAlmostEqual(
            report["mean_gross_return_pct"] - report["cost_pct"],
            report["mean_net_return_pct"],
        )

    def test_funding_strength_signal_includes_current_but_not_future_funding(self):
        candles = self.candles([100.0] * 50)
        original = {
            "A": (self.funding_points([0.01, 0.03, -0.5], step=10), candles),
            "B": (self.funding_points([-0.01, -0.03, 0.5], step=10), candles),
        }
        altered = {
            "A": (self.funding_points([0.01, 0.03, 0.5], step=10), candles),
            "B": (self.funding_points([-0.01, -0.03, -0.5], step=10), candles),
        }
        kwargs = {
            "lookback_settlements": 2,
            "holding_settlements": 1,
            "min_market_appearances": 0,
            "settlement_interval_ms": 10,
            "candle_interval_ms": 1,
            "bootstrap_samples": 20,
        }
        first = funding_relative_strength_report(original, **kwargs)
        changed = funding_relative_strength_report(altered, **kwargs)

        self.assertAlmostEqual(first["records"][0]["scores"]["A"], 0.02)
        self.assertEqual(first["records"][0]["long_market"], "A")
        self.assertEqual(changed["records"][0]["long_market"], "A")
        self.assertEqual(first["records"][0]["scores"], changed["records"][0]["scores"])
        self.assertNotEqual(
            first["records"][0]["net_return_pct"],
            changed["records"][0]["net_return_pct"],
        )

    def test_funding_strength_events_do_not_overlap(self):
        candles = self.candles([100.0] * 70)
        markets = {
            "A": (self.funding_points([0.01] * 6, step=10), candles),
            "B": (self.funding_points([-0.01] * 6, step=10), candles),
        }
        report = funding_relative_strength_report(
            markets,
            1,
            1,
            min_market_appearances=0,
            settlement_interval_ms=10,
            candle_interval_ms=1,
            bootstrap_samples=20,
        )

        self.assertGreater(len(report["records"]), 1)
        for previous, current in zip(report["records"], report["records"][1:]):
            self.assertGreater(
                current["long_entry_time_ms"], previous["exit_time_ms"],
            )

    def test_funding_strength_coverage_gate_rejects_fixed_pair(self):
        slots = 72
        funding = {
            "A": self.funding_points([0.001] * slots, step=10),
            "B": self.funding_points([-0.001] * slots, step=10),
            "C": self.funding_points([0.0002] * slots, step=10),
            "D": self.funding_points([-0.0002] * slots, step=10),
        }
        candles = {
            "A": self.candles([100 * (1.002 ** index) for index in range(750)]),
            "B": self.candles([100 * (0.998 ** index) for index in range(750)]),
            "C": self.candles([100.0] * 750),
            "D": self.candles([100.0] * 750),
        }
        report = funding_relative_strength_report(
            {name: (funding[name], candles[name]) for name in funding},
            1,
            1,
            min_market_appearances=10,
            settlement_interval_ms=10,
            candle_interval_ms=1,
            bootstrap_samples=200,
        )

        self.assertGreaterEqual(report["events"], 30)
        self.assertTrue(report["statistical_admitted"])
        self.assertFalse(report["coverage_admitted"])
        self.assertFalse(report["admitted"])

    def test_bootstrap_mean_interval_is_deterministic(self):
        first = bootstrap_mean_interval([0.1, 0.2, 0.3], samples=100, seed=7)
        second = bootstrap_mean_interval([0.1, 0.2, 0.3], samples=100, seed=7)

        self.assertEqual(first, second)

    def test_sine_market_reverts_every_excursion(self):
        reversions, extensions = excursion_outcomes(sine_series(), a_pct=1.5, theta_pct=4.0)
        self.assertGreater(reversions, 10)
        self.assertEqual(extensions, 0)

    def test_monotone_market_extends_every_excursion(self):
        reversions, extensions = excursion_outcomes(monotone_series(), a_pct=1.5, theta_pct=4.0)
        self.assertEqual(reversions, 0)
        self.assertGreater(extensions, 5)

    def test_estimate_admits_reverting_market(self):
        report = estimate(sine_series(), 1.5, 4.0, 0.14)
        self.assertTrue(report["admitted"])
        self.assertGreater(report["expected_value_pct"], 0)

    def test_estimate_rejects_trending_market(self):
        report = estimate(monotone_series(), 1.5, 4.0, 0.14)
        self.assertFalse(report["admitted"])
        self.assertLess(report["expected_value_pct"], 0)

    def test_return_attribution_reconciles_gross_fees_and_net(self):
        report = estimate(sine_series(), 1.5, 4.0, 0.14)

        self.assertAlmostEqual(
            report["gross_return_pct"] - report["fee_drag_pct"],
            report["total_return_pct"],
        )
        self.assertAlmostEqual(
            report["break_even_cost_pct"],
            report["gross_return_pct"] / report["excursions"],
        )

    def test_wilson_interval_shrinks_with_samples(self):
        low_small, high_small = wilson_interval(7, 10)
        low_big, high_big = wilson_interval(700, 1000)
        self.assertLess(high_big - low_big, high_small - low_small)

    def test_geometry_scan_orders_by_expected_value(self):
        rows = geometry_scan(sine_series(), [1.0, 1.5], [3.0, 4.0], 0.14)
        values = [row["expected_value_pct"] for row in rows]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_invalid_geometry_raises(self):
        with self.assertRaises(ValueError):
            excursion_outcomes([100, 101], a_pct=4.0, theta_pct=3.0)

    def test_regime_gate_filters_monotone_entries(self):
        report = gated_estimate(
            monotone_series(ticks=600),
            1.5,
            4.0,
            0.14,
            gate_config={"window": 20, "min_samples": 10, "confirm_ticks": 1},
        )

        self.assertGreater(report["filtered_entries"], 0)
        self.assertEqual(report["excursions"], 0)
        self.assertEqual(report["filtered_reversions"], 0)
        self.assertEqual(report["filtered_extensions"], report["filtered_entries"])
        self.assertLess(report["filtered_counterfactual_net_return_pct"], 0)

    def test_regime_gate_keeps_range_entries(self):
        report = gated_estimate(
            sine_series(cycles=40),
            1.5,
            4.0,
            0.14,
            gate_config={
                "window": 48,
                "min_samples": 20,
                "confirm_ticks": 1,
                "range_max_autocorrelation": 1.0,
            },
        )

        self.assertGreater(report["excursions"], 10)
        self.assertGreater(report["trade_frequency"], 0.5)

    def test_max_drawdown_uses_peak_to_trough_loss(self):
        self.assertAlmostEqual(max_drawdown([1.0, -0.5, -2.0, 1.0]), 2.5)

    def test_walk_forward_uses_disjoint_train_and_validation_windows(self):
        closes = sine_series(cycles=12, ticks_per_cycle=20)
        result = walk_forward_compare(
            closes,
            [1.0, 1.5],
            [3.0, 4.0],
            0.14,
            train_size=100,
            validation_size=40,
            step=40,
        )

        self.assertEqual(len(result["folds"]), 3)
        self.assertEqual(result["folds"][0]["train_end"], 100)
        self.assertEqual(result["folds"][0]["validation_end"], 140)
        self.assertEqual(result["folds"][1]["train_start"], 40)

    def test_gate_counterfactual_reconciles_with_unfiltered_result(self):
        closes = monotone_series(ticks=240)
        result = walk_forward_compare(
            closes,
            [1.0],
            [3.0],
            0.14,
            train_size=100,
            validation_size=40,
            step=40,
        )

        for fold in result["folds"]:
            self.assertAlmostEqual(
                fold["gate_on"]["counterfactual_unfiltered_total_return_pct"],
                fold["gate_off"]["total_return_pct"],
            )

    def test_aggregate_reports_weights_each_fold_actual_geometry(self):
        first = estimate(sine_series(cycles=3), 1.0, 3.0, 0.14)
        second = estimate(monotone_series(ticks=100), 1.5, 4.0, 0.14)
        aggregate = aggregate_reports([first, second], 0.14)

        expected_total = first["total_return_pct"] + second["total_return_pct"]
        self.assertAlmostEqual(aggregate["total_return_pct"], expected_total)
        self.assertEqual(len(aggregate["geometries"]), 2)
        self.assertAlmostEqual(
            aggregate["expected_value_pct"],
            expected_total / aggregate["excursions"],
        )

    def test_portfolio_stage_gate_requires_profitable_market_majority(self):
        positive = walk_forward_compare(
            sine_series(cycles=12, ticks_per_cycle=20),
            [1.0],
            [3.0],
            0.14,
            train_size=100,
            validation_size=40,
            step=40,
            gate_config={"range_max_autocorrelation": 1.0, "confirm_ticks": 1},
        )
        negative = walk_forward_compare(
            monotone_series(ticks=240),
            [1.0],
            [3.0],
            0.14,
            train_size=100,
            validation_size=40,
            step=40,
        )
        markets = [
            {"name": "positive", "result": positive},
            {"name": "negative-1", "result": negative},
            {"name": "negative-2", "result": negative},
        ]

        summary = portfolio_calibration_summary(markets, 0.14, comparison="gate_off")

        self.assertEqual(summary["markets"], 3)
        self.assertEqual(summary["required_profitable_markets"], 2)
        self.assertEqual(summary["profitable_markets"], 1)
        self.assertFalse(summary["stage_admitted"])

    def test_gate_selection_rejects_too_sparse_candidate(self):
        closes = sine_series(cycles=20)
        configs = [
            {"window": 30, "min_samples": 20, "range_efficiency_ratio": -1.0},
            {
                "window": 48,
                "min_samples": 20,
                "confirm_ticks": 1,
                "range_max_autocorrelation": 1.0,
            },
        ]

        selected, report = select_gate_config(closes, 1.5, 4.0, 0.14, configs)

        self.assertEqual(selected["window"], 48)
        self.assertTrue(report["selection_eligible"])
        self.assertGreaterEqual(report["excursions"], report["minimum_selection_trades"])

    def test_gate_tuning_does_not_read_validation_prices(self):
        closes = sine_series(cycles=12, ticks_per_cycle=20)
        altered = list(closes)
        altered[100:140] = monotone_series(ticks=40)
        kwargs = {
            "a_grid": [1.0, 1.5],
            "theta_grid": [3.0, 4.0],
            "cost_pct": 0.14,
            "train_size": 100,
            "validation_size": 40,
            "step": 40,
            "gate_config_grid": default_gate_config_grid(),
        }

        original = walk_forward_compare(closes, **kwargs)
        changed = walk_forward_compare(altered, **kwargs)

        self.assertTrue(original["gate_tuning_enabled"])
        self.assertEqual(
            original["folds"][0]["selected_gate_config"],
            changed["folds"][0]["selected_gate_config"],
        )
        self.assertEqual(
            original["folds"][0]["gate_training"],
            changed["folds"][0]["gate_training"],
        )

    def test_unqualified_training_fold_abstains_in_deploy_comparison(self):
        result = walk_forward_compare(
            monotone_series(ticks=240),
            [1.0],
            [3.0],
            0.14,
            train_size=100,
            validation_size=40,
            step=40,
            gate_config_grid=default_gate_config_grid(),
        )

        self.assertFalse(result["folds"][0]["gate_qualified"])
        self.assertEqual(result["folds"][0]["gate_deploy"]["excursions"], 0)
        self.assertGreater(result["folds"][0]["gate_deploy"]["filtered_entries"], 0)


if __name__ == "__main__":
    unittest.main()
