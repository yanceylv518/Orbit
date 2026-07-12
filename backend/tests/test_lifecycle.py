import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.strategy.actions import StrategyActionSet
from orbit.domain.strategy.exposure import decide_target_exposure
from orbit.domain.strategy.lifecycle import StrategyLifecycle


class StrategyLifecycleTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.lifecycle = StrategyLifecycle(self.strategy)

    def test_profit_transfer_updates_trend_scope_counters(self):
        state = self.state()
        decision = self.decide("102")

        self.lifecycle.apply_event(state, Decimal("102"), decision, self.action_set("PROFIT_TRANSFER_UP"))

        self.assertEqual(state["state"], "SKEWED_SHORT")
        self.assertEqual(state["profit_transfer_count_in_trend"], 1)
        self.assertEqual(state["last_transfer_tick"], 7)
        self.assertEqual(state["last_transfer_price"], "102")
        self.assertEqual(state["trend_extreme_price"], "102")

    def test_recovery_reanchors_and_clears_trend_scope(self):
        state = self.state()
        state.update({
            "state": "REANCHORING",
            "long_qty": "0.95",
            "short_qty": "0.98",
            "profit_transfer_count_in_trend": 2,
            "loss_side_reduce_count_in_trend": 1,
            "recovery_count_in_trend": 1,
            "last_transfer_tick": 4,
            "last_loss_reduce_tick": 5,
            "last_transfer_price": "102",
            "last_loss_reduce_price": "105",
        })
        decision = self.decide("100.2", long_qty="0.95", short_qty="1")

        self.lifecycle.apply_event(state, Decimal("100.2"), decision, self.action_set("POSITION_RECOVERY_UP"))

        self.assertEqual(state["state"], "BALANCED")
        self.assertEqual(state["base_price"], "100.2")
        self.assertEqual(state["base_qty"], "0.39920159")
        self.assertEqual(state["profit_transfer_count_in_trend"], 0)
        self.assertEqual(state["loss_side_reduce_count_in_trend"], 0)
        self.assertEqual(state["recovery_count_in_trend"], 0)
        self.assertIsNone(state["last_transfer_price"])
        self.assertIsNone(state["last_loss_reduce_price"])

    def test_recovery_waits_for_legs_to_rebuild_before_reanchor(self):
        state = self.state()
        state.update({
            "state": "REANCHORING",
            "long_qty": "0.8",
            "short_qty": "0.82",
            "profit_transfer_count_in_trend": 2,
            "last_transfer_tick": 4,
            "last_transfer_price": "102",
        })
        decision = self.decide("100.2", long_qty="0.8", short_qty="1")

        self.lifecycle.apply_event(state, Decimal("100.2"), decision, self.action_set("POSITION_RECOVERY_UP"))

        self.assertEqual(state["state"], "REANCHORING")
        self.assertEqual(state["base_price"], "100")
        self.assertEqual(state["profit_transfer_count_in_trend"], 2)
        self.assertEqual(state["recovery_count_in_trend"], 1)

    def test_trend_tracking_counts_exit_candidate_ticks(self):
        state = self.state()
        state.update({
            "state": "TREND_UP",
            "base_price": "100",
            "high_since_base": "106",
            "trend_extreme_price": "106",
        })

        self.lifecycle.update_trend_tracking(state, Decimal("102.5"))
        self.lifecycle.update_trend_tracking(state, Decimal("102.4"))

        self.assertEqual(state["trend_extreme_price"], "106")
        self.assertEqual(state["trend_exit_candidate_count"], 2)

    def test_trend_tracking_resets_exit_candidate_outside_return_band(self):
        state = self.state()
        state.update({
            "state": "TREND_UP",
            "base_price": "100",
            "high_since_base": "106",
            "trend_extreme_price": "106",
            "trend_exit_candidate_count": 1,
        })

        self.lifecycle.update_trend_tracking(state, Decimal("103.5"))

        self.assertEqual(state["trend_exit_candidate_count"], 0)

    def test_resolve_state_keeps_trend_state_absorbed_until_recovery(self):
        state = self.state()
        state["state"] = "TREND_UP"
        state["long_qty"] = "1"
        state["short_qty"] = "1"

        self.assertEqual(self.lifecycle.resolve_state(state), "TREND_UP")

    def state(self):
        return {
            "state": "BALANCED",
            "base_price": "100",
            "high_since_base": "100",
            "low_since_base": "100",
            "trend_extreme_price": "100",
            "base_qty": "1",
            "long_qty": "1",
            "short_qty": "1",
            "tick_count": 7,
            "profit_transfer_count_in_trend": 0,
            "loss_side_reduce_count_in_trend": 0,
            "recovery_count_in_trend": 0,
            "trend_exit_candidate_count": 0,
            "last_transfer_tick": -999999,
            "last_loss_reduce_tick": -999999,
            "last_transfer_price": None,
            "last_loss_reduce_price": None,
        }

    def decide(self, price, long_qty="1", short_qty="1"):
        return decide_target_exposure(
            price=Decimal(str(price)),
            base_price=Decimal("100"),
            base_qty=Decimal("1"),
            long_qty=Decimal(str(long_qty)),
            short_qty=Decimal(str(short_qty)),
            strategy=self.strategy,
        )

    def action_set(self, event_type):
        return StrategyActionSet(
            event_type=event_type,
            direction="UP",
            reason="test",
            actions=[],
            sizing={},
            trigger={},
        )


if __name__ == "__main__":
    unittest.main()
