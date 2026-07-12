import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.risk.guards import RiskContext, RiskPolicy, guard_actions


class RiskGuardTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.context = RiskContext(
            symbol="BTCUSDT",
            price=Decimal("100"),
            long_qty=Decimal("1"),
            short_qty=Decimal("1"),
            budget_usdt=Decimal("100"),
        )

    def test_run_config_blocks_add_but_allows_reduce(self):
        policy = RiskPolicy.from_config(
            self.strategy,
            {"mode": "plan_only", "allow_reduce_only": True, "allow_add_position": False},
            enforce_plan_only=True,
        )

        result = guard_actions([
            self.action("REDUCE_LONG", "0.2"),
            self.action("ADD_SHORT", "0.2"),
        ], self.context, policy)

        self.assertEqual(result.actions[0]["status"], "planned")
        self.assertEqual(result.actions[1]["status"], "blocked")
        self.assertEqual(result.actions[1]["block_code"], "ADD_POSITION_DISABLED")

    def test_gross_limit_blocks_add_and_keeps_reduce_open(self):
        policy = RiskPolicy.from_config(
            self.strategy,
            {"mode": "plan_only", "allow_reduce_only": False, "allow_add_position": True},
            enforce_plan_only=True,
        )
        context = RiskContext(
            symbol="BTCUSDT",
            price=Decimal("100"),
            long_qty=Decimal("1.2"),
            short_qty=Decimal("1.0"),
            budget_usdt=Decimal("100"),
        )

        result = guard_actions([
            self.action("REDUCE_LONG", "0.1"),
            self.action("ADD_SHORT", "0.1"),
        ], context, policy)

        self.assertTrue(result.state.gross_exceeded)
        self.assertEqual(result.actions[0]["status"], "planned")
        self.assertEqual(result.actions[1]["status"], "blocked")
        self.assertEqual(result.actions[1]["block_code"], "ONLY_REDUCE")

    def test_symbol_stop_allows_only_stop_unwind_actions(self):
        policy = RiskPolicy.from_config(
            self.strategy,
            {"mode": "plan_only", "allow_reduce_only": False, "allow_add_position": True},
            enforce_plan_only=True,
        )
        context = RiskContext(
            symbol="BTCUSDT",
            price=Decimal("100"),
            long_qty=Decimal("1"),
            short_qty=Decimal("1"),
            budget_usdt=Decimal("100"),
            realized_pnl=Decimal("-11"),
        )

        result = guard_actions([
            self.action("REDUCE_LONG", "0.1"),
            self.action("REDUCE_SHORT", "1", risk_intent="STOP_UNWIND"),
        ], context, policy)

        self.assertTrue(result.stopped)
        self.assertEqual(result.actions[0]["status"], "blocked")
        self.assertEqual(result.actions[0]["block_code"], "SYMBOL_STOPPED")
        self.assertEqual(result.actions[1]["status"], "planned")

    def action(self, name, qty, risk_intent="STRATEGY"):
        quantity = Decimal(str(qty))
        return {
            "action": name,
            "quantity": float(quantity),
            "notional_usdt": float(quantity * Decimal("100")),
            "status": "planned",
            "risk_intent": risk_intent,
        }


if __name__ == "__main__":
    unittest.main()
