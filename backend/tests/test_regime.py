import math
import sys
import unittest
from decimal import Decimal
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.strategy.exposure import TargetExposureDecision
from orbit.domain.strategy.regime import (
    RANGE,
    TRANSITION,
    TRENDING,
    UNKNOWN,
    RegimeGate,
    classify_regime,
)


def strategy_config(**overrides):
    config = {
        "enabled": True,
        "window": 30,
        "min_samples": 20,
        "confirm_ticks": 3,
        "range_efficiency_ratio": 0.35,
        "trend_efficiency_ratio": 0.65,
        "range_max_autocorrelation": 0.95,
        "min_volatility_pct": 0.001,
    }
    config.update(overrides)
    return {"strategy": {"regime_gate": config}}


def decision(event_type):
    return TargetExposureDecision(
        event_type=event_type,
        direction="UP",
        lifecycle_state="BALANCED",
        reason="test",
        price=Decimal("102"),
        base_price=Decimal("100"),
        move_pct=Decimal("2"),
        current_net_qty=Decimal("0"),
        target_net_qty=Decimal("-1"),
        delta_qty=Decimal("-1"),
        base_qty=Decimal("1"),
        step_count=1,
    )


class RegimeClassifierTests(unittest.TestCase):
    def test_insufficient_history_is_unknown(self):
        regime, features = classify_regime([100, 101, 100], strategy_config()["strategy"]["regime_gate"])

        self.assertEqual(regime, UNKNOWN)
        self.assertEqual(features.sample_count, 3)

    def test_oscillating_market_is_range(self):
        prices = [100 + 2 * math.sin(2 * math.pi * index / 12) for index in range(36)]
        regime, features = classify_regime(prices, strategy_config()["strategy"]["regime_gate"])

        self.assertEqual(regime, RANGE)
        self.assertLess(features.efficiency_ratio, 0.35)

    def test_monotone_market_is_trending(self):
        prices = [100 + index for index in range(30)]
        regime, features = classify_regime(prices, strategy_config()["strategy"]["regime_gate"])

        self.assertEqual(regime, TRENDING)
        self.assertEqual(features.efficiency_ratio, 1.0)

    def test_low_er_with_extreme_positive_autocorrelation_is_not_range(self):
        prices = [100.0]
        for change in ([0.001] * 60 + [-0.001] * 60):
            prices.append(prices[-1] * (1 + change))

        regime, features = classify_regime(prices, strategy_config()["strategy"]["regime_gate"])

        self.assertLess(features.efficiency_ratio, 0.35)
        self.assertGreater(features.return_autocorrelation, 0.95)
        self.assertEqual(regime, TRANSITION)

    def test_low_er_with_low_autocorrelation_is_range(self):
        prices = [100 + 2 * math.sin(2 * math.pi * index / 12) for index in range(120)]

        regime, features = classify_regime(prices, strategy_config()["strategy"]["regime_gate"])

        self.assertLess(features.efficiency_ratio, 0.35)
        self.assertLess(features.return_autocorrelation, 0.95)
        self.assertEqual(regime, RANGE)

    def test_state_transition_requires_confirmation(self):
        gate = RegimeGate(strategy_config(window=6, min_samples=4, confirm_ticks=2))
        state = {}
        for price in (100, 101, 102, 103):
            gate.update(state, price)

        self.assertEqual(state["regime"], TRANSITION)
        gate.update(state, 104)
        self.assertEqual(state["regime"], TRENDING)
        self.assertEqual(state["regime_stable"], TRENDING)


class RegimeGatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.gate = RegimeGate(strategy_config())

    def test_unknown_blocks_new_grid_skew(self):
        result = self.gate.evaluate(decision("PROFIT_TRANSFER_UP"), {"regime": UNKNOWN})

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "REGIME_UNKNOWN_BLOCKED")

    def test_range_allows_new_grid_skew(self):
        result = self.gate.evaluate(decision("PROFIT_TRANSFER_UP"), {"regime": RANGE})

        self.assertTrue(result.allowed)
        self.assertEqual(result.code, "REGIME_RANGE_ALLOWED")

    def test_trending_still_allows_loss_reduction(self):
        result = self.gate.evaluate(decision("LOSS_SIDE_REDUCTION_UP"), {"regime": TRENDING})

        self.assertTrue(result.allowed)
        self.assertEqual(result.code, "REGIME_RISK_REDUCTION_ALLOWED")

    def test_transition_blocks_position_rebuild(self):
        result = self.gate.evaluate(decision("POSITION_REBUILD"), {"regime": TRANSITION})

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "REGIME_TRANSITION_BLOCKED")


if __name__ == "__main__":
    unittest.main()
