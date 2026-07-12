import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.strategy.exposure import decide_target_exposure
from orbit.domain.strategy.rules.event_rules import StrategyEventRules


class EventRulesTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.rules = StrategyEventRules(self.strategy)
        self.state = {
            "state": "BALANCED",
            "base_price": "100",
            "tick_count": 10,
            "profit_transfer_count_in_trend": 0,
            "trend_exit_candidate_count": 0,
            "last_transfer_tick": -999999,
            "last_loss_reduce_tick": -999999,
            "last_loss_reduce_price": None,
        }

    def test_profit_transfer_rule_blocks_after_max_times(self):
        decision = self.decide("102")
        state = dict(self.state)
        state["profit_transfer_count_in_trend"] = 3

        result = self.rules.evaluate(decision, state, Decimal("102"))

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "MAX_TIMES_PER_TREND")

    def test_profit_transfer_rule_blocks_during_cooldown(self):
        decision = self.decide("102")
        state = dict(self.state)
        state["tick_count"] = 12
        state["last_transfer_tick"] = 10

        result = self.rules.evaluate(decision, state, Decimal("102"))

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "COOLDOWN_ACTIVE")

    def test_profit_transfer_rule_blocks_while_trend_confirmed(self):
        decision = self.decide("102")
        state = dict(self.state)
        state["state"] = "TREND_UP"

        result = self.rules.evaluate(decision, state, Decimal("102"))

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "TREND_CONFIRMED")

    def test_trend_reduction_rule_blocks_until_next_step(self):
        decision = self.decide("104")

        result = self.rules.evaluate(decision, dict(self.state), Decimal("104"))

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "TREND_STEP_NOT_REACHED")

    def test_trend_reduction_rule_allows_step_price(self):
        decision = self.decide("105")

        result = self.rules.evaluate(decision, dict(self.state), Decimal("105"))

        self.assertTrue(result.allowed)
        self.assertEqual(result.code, "LOSS_SIDE_REDUCTION_ALLOWED")

    def test_position_recovery_blocks_until_trend_exit_is_confirmed(self):
        decision = self.decide("100.2", long_qty="1", short_qty="0.3")
        state = dict(self.state)
        state.update({"state": "TREND_UP", "trend_exit_candidate_count": 1})

        result = self.rules.evaluate(decision, state, Decimal("100.2"))

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "TREND_EXIT_NOT_CONFIRMED")

    def test_position_recovery_allows_after_trend_exit_confirmation(self):
        decision = self.decide("100.2", long_qty="1", short_qty="0.3")
        state = dict(self.state)
        state.update({"state": "TREND_UP", "trend_exit_candidate_count": 2})

        result = self.rules.evaluate(decision, state, Decimal("100.2"))

        self.assertTrue(result.allowed)
        self.assertEqual(result.code, "POSITION_RECOVERY_ALLOWED")

    def decide(self, price, long_qty="1", short_qty="1"):
        return decide_target_exposure(
            price=Decimal(str(price)),
            base_price=Decimal("100"),
            base_qty=Decimal("1"),
            long_qty=Decimal(str(long_qty)),
            short_qty=Decimal(str(short_qty)),
            strategy=self.strategy,
        )


if __name__ == "__main__":
    unittest.main()
