import math
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (
    aggregate_reports,
    default_gate_config_grid,
    estimate,
    excursion_outcomes,
    expected_value_per_bet,
    gated_estimate,
    geometry_scan,
    max_drawdown,
    pi_required,
    portfolio_calibration_summary,
    select_gate_config,
    walk_forward_compare,
    wilson_interval,
)


def sine_series(base=100.0, amplitude_pct=2.5, cycles=20, ticks_per_cycle=48):
    return [
        base * (1 + amplitude_pct / 100 * math.sin(2 * math.pi * i / ticks_per_cycle))
        for i in range(cycles * ticks_per_cycle)
    ]


def monotone_series(base=100.0, step_pct=0.2, ticks=400):
    return [base * (1 + step_pct / 100) ** i for i in range(ticks)]


class EstimatorTest(unittest.TestCase):
    def test_pi_required_matches_strategy_logic_formula(self):
        # STRATEGY_LOGIC §2：a=1.5, θ=4, c=0.14 → π_req = 1 − 1.36/4 = 0.66
        self.assertAlmostEqual(pi_required(1.5, 4.0, 0.14), 0.66, places=3)

    def test_expected_value_zero_at_required_pi(self):
        required = pi_required(1.5, 4.0, 0.14)
        self.assertAlmostEqual(expected_value_per_bet(required, 1.5, 4.0, 0.14), 0.0, places=9)

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
