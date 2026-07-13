import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.strategy.actions import StrategyLeg, StrategyPosition, build_strategy_action_set
from orbit.domain.strategy.exposure import decide_target_exposure


class StrategyActionsTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]

    def test_profit_transfer_builds_reduce_and_inverse_add_actions(self):
        decision = self.decide(price="102")
        action_set = build_strategy_action_set(
            decision,
            self.position(price="102", long_pnl="2", short_pnl="-2"),
            self.strategy,
        )

        self.assertIsNotNone(action_set)
        self.assertEqual(action_set.event_type, "PROFIT_TRANSFER_UP")
        self.assertEqual([item.action for item in action_set.actions], ["REDUCE_LONG", "ADD_SHORT"])
        self.assertEqual([item.event_role for item in action_set.actions], ["REDUCE_PROFIT_SIDE", "ADD_LOSS_SIDE"])
        self.assertEqual(action_set.trigger["profit_side"], "LONG")

    def test_profit_transfer_can_require_add_leg_roundtrip_coverage(self):
        strategy = deepcopy(self.strategy)
        sizing = strategy["strategy"]["events"]["profit_transfer"]["sizing"]
        sizing["min_net_profit_usdt"] = 0.1928
        decision = self.decide(price="102")
        position = self.position(price="102", long_pnl="2", short_pnl="-2")

        sizing["require_add_leg_roundtrip_coverage"] = False
        without_coverage = build_strategy_action_set(decision, position, strategy)
        sizing["require_add_leg_roundtrip_coverage"] = True
        with_coverage = build_strategy_action_set(decision, position, strategy)

        self.assertIsNotNone(without_coverage)
        self.assertIsNone(with_coverage)
        projected = Decimal(without_coverage.sizing["projected_net_realized"])
        roundtrip_cost = Decimal(without_coverage.sizing["estimated_add_leg_roundtrip_cost"])
        self.assertGreater(projected, Decimal("0.1928"))
        self.assertLess(projected, Decimal("0.1928") + roundtrip_cost)

    def test_profit_transfer_reduces_profit_leg_when_loss_leg_is_above_base(self):
        decision = self.decide(price="102", long_qty="1.2", short_qty="1.2")
        position = self.position(
            price="102", long_qty="1.2", short_qty="1.2", long_pnl="2.4", short_pnl="-2.4",
        )

        action_set = build_strategy_action_set(decision, position, self.strategy)

        self.assertGreaterEqual(position.short.qty, decision.base_qty)
        self.assertIsNotNone(action_set)
        self.assertEqual(action_set.actions[0].action, "REDUCE_LONG")
        self.assertEqual(action_set.actions[0].event_role, "REDUCE_PROFIT_SIDE")

    def test_trend_reduction_builds_loss_side_reduce_action(self):
        decision = self.decide(price="105")
        action_set = build_strategy_action_set(
            decision,
            self.position(price="105", long_pnl="5", short_pnl="-5"),
            self.strategy,
        )

        self.assertIsNotNone(action_set)
        self.assertEqual(action_set.event_type, "LOSS_SIDE_REDUCTION_UP")
        self.assertEqual(action_set.actions[0].action, "REDUCE_SHORT")
        self.assertEqual(action_set.actions[0].event_role, "LOSS_SIDE_REDUCTION")
        self.assertEqual(action_set.trigger["loss_side"], "SHORT")

    def test_neutralization_geometry_reduces_full_counter_trend_delta(self):
        strategy = deepcopy(self.strategy)
        strategy["strategy"]["events"]["loss_side_reduction"]["sizing"][
            "neutralize_counter_trend_skew_only"
        ] = True
        decision = self.decide(price="105", long_qty="0.7", short_qty="1.0", strategy=strategy)

        action_set = build_strategy_action_set(
            decision,
            self.position(price="105", long_qty="0.7", short_qty="1.0", long_pnl="3.5", short_pnl="-5"),
            strategy,
        )

        self.assertIsNotNone(action_set)
        self.assertEqual(action_set.actions[0].action, "REDUCE_SHORT")
        self.assertEqual(action_set.actions[0].quantity, Decimal("0.30000000"))
        self.assertEqual(action_set.sizing["geometry"], "neutralize_counter_trend_skew")

    def test_recovery_builds_reduce_heavy_side_action(self):
        decision = self.decide(price="100.2", long_qty="0.7", short_qty="1.0")
        action_set = build_strategy_action_set(
            decision,
            self.position(price="100.2", long_qty="0.7", short_qty="1.0", long_pnl="0", short_pnl="0"),
            self.strategy,
        )

        self.assertIsNotNone(action_set)
        self.assertEqual(action_set.event_type, "POSITION_RECOVERY_UP")
        self.assertEqual(action_set.actions[0].action, "REDUCE_SHORT")
        self.assertEqual(action_set.actions[0].event_role, "POSITION_RECOVERY")

    def test_rebuild_builds_capped_add_actions_for_both_legs(self):
        decision = self.decide(price="100.2", long_qty="0.7", short_qty="0.7")
        action_set = build_strategy_action_set(
            decision,
            self.position(price="100.2", long_qty="0.7", short_qty="0.7", long_pnl="0", short_pnl="0"),
            self.strategy,
        )

        self.assertIsNotNone(action_set)
        self.assertEqual(action_set.event_type, "POSITION_REBUILD")
        self.assertEqual([item.action for item in action_set.actions], ["ADD_LONG", "ADD_SHORT"])
        self.assertEqual([item.event_role for item in action_set.actions], ["POSITION_REBUILD", "POSITION_REBUILD"])
        self.assertEqual(action_set.sizing["add_long_qty"], "0.20000000")
        self.assertEqual(action_set.sizing["add_short_qty"], "0.20000000")

    def decide(self, price, long_qty="1", short_qty="1", strategy=None):
        return decide_target_exposure(
            price=Decimal(str(price)),
            base_price=Decimal("100"),
            base_qty=Decimal("1"),
            long_qty=Decimal(str(long_qty)),
            short_qty=Decimal(str(short_qty)),
            strategy=strategy or self.strategy,
        )

    def position(self, price, long_qty="1", short_qty="1", long_pnl="0", short_pnl="0"):
        price = Decimal(str(price))
        return StrategyPosition(
            symbol="BTCUSDT",
            price=price,
            budget_usdt=Decimal("100"),
            base_position_usdt=Decimal("40"),
            long=StrategyLeg(
                side="LONG",
                qty=Decimal(str(long_qty)),
                entry_price=Decimal("100"),
                mark_price=price,
                unrealized_pnl=Decimal(str(long_pnl)),
                notional=Decimal(str(long_qty)) * price,
            ),
            short=StrategyLeg(
                side="SHORT",
                qty=Decimal(str(short_qty)),
                entry_price=Decimal("100"),
                mark_price=price,
                unrealized_pnl=Decimal(str(short_pnl)),
                notional=Decimal(str(short_qty)) * price,
            ),
        )


if __name__ == "__main__":
    unittest.main()
