import math
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (
    estimate,
    excursion_outcomes,
    expected_value_per_bet,
    geometry_scan,
    pi_required,
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


if __name__ == "__main__":
    unittest.main()
