import time
import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.planning.plans import generate_account_execution_plans
from orbit.domain.risk.guards import RiskContext, RiskPolicy, guard_actions


def base_context(**overrides):
    values = {
        "symbol": "BTCUSDT",
        "price": Decimal("60000"),
        "long_qty": Decimal("0.001"),
        "short_qty": Decimal("0.001"),
        "budget_usdt": Decimal("100"),
    }
    values.update(overrides)
    return RiskContext(**values)


def base_policy(**overrides):
    values = {
        "max_symbol_drawdown_pct": Decimal("10"),
        "max_gross_exposure_ratio": Decimal("5"),
        "allow_add_position": True,
        "loss_side_budget_ratio": Decimal("0.8"),
    }
    values.update(overrides)
    return RiskPolicy(**values)


class C7SelfFundingGuardTest(unittest.TestCase):
    def test_add_loss_side_blocked_without_harvested_profit(self):
        actions = [{
            "action": "ADD_SHORT",
            "quantity": 0.0005,
            "notional_usdt": 30,
            "event_role": "ADD_LOSS_SIDE",
        }]
        result = guard_actions(actions, base_context(), base_policy())
        self.assertEqual(result.actions[0]["status"], "blocked")
        self.assertEqual(result.actions[0]["block_code"], "C7_SELF_FUNDING")

    def test_add_loss_side_allowed_within_harvested_budget(self):
        actions = [{
            "action": "ADD_SHORT",
            "quantity": 0.0005,
            "notional_usdt": 30,
            "event_role": "ADD_LOSS_SIDE",
        }]
        context = base_context(harvested_profit_usdt=Decimal("50"))
        result = guard_actions(actions, context, base_policy())
        self.assertEqual(result.actions[0]["status"], "planned")

    def test_same_set_reduce_profit_funds_the_add(self):
        # 同组先减盈利腿（浮盈 40，将实现 ~20），再加亏损腿 15 → 应被自融资覆盖
        actions = [
            {"action": "REDUCE_LONG", "quantity": 0.0005, "notional_usdt": 30, "event_role": "REDUCE_PROFIT_SIDE"},
            {"action": "ADD_SHORT", "quantity": 0.00025, "notional_usdt": 15, "event_role": "ADD_LOSS_SIDE"},
        ]
        context = base_context(long_unrealized_pnl=Decimal("40"))
        result = guard_actions(actions, context, base_policy())
        statuses = [item["status"] for item in result.actions]
        self.assertEqual(statuses, ["planned", "planned"])


class PortfolioStopGuardTest(unittest.TestCase):
    def test_portfolio_stop_blocks_all_but_stop_unwind(self):
        actions = [
            {"action": "ADD_LONG", "quantity": 0.001, "notional_usdt": 60},
            {"action": "REDUCE_SHORT", "quantity": 0.0005, "notional_usdt": 30},
            {"action": "REDUCE_LONG", "quantity": 0.001, "notional_usdt": 60, "risk_intent": "STOP_UNWIND"},
        ]
        result = guard_actions(actions, base_context(), base_policy(portfolio_stopped=True))
        codes = [item.get("block_code") for item in result.actions]
        self.assertEqual(codes[0], "GLOBAL_STOP")
        self.assertEqual(codes[1], "GLOBAL_STOP")
        self.assertIsNone(codes[2])
        self.assertTrue(any(check["name"] == "portfolio_stop" and not check["ok"] for check in result.checks))


class SnapshotStalenessTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.run_config = {**cfg["account_run_configs"][0], "enabled": True}
        self.account = {"id": "acct_a", "user_id": "user_001"}

    def snapshot(self, synced_at):
        return {
            "status": "synced",
            "synced_at": synced_at,
            "position_mode": {"hedge_mode_ok": True},
            "positions": [{
                "symbol": "BTCUSDT",
                "position_side": "LONG",
                "position_amt": 0.001,
                "entry_price": 60000,
                "mark_price": 60000,
                "unrealized_profit": 0,
                "notional": 60,
            }],
        }

    def test_stale_snapshot_blocks_plan_generation(self):
        stale_ms = int(time.time() * 1000) - 3600_000
        plans = generate_account_execution_plans(
            self.account, self.run_config, self.strategy,
            self.snapshot(stale_ms), snapshot_max_age_seconds=600,
        )
        self.assertEqual(plans[0]["event_type"], "SYNC_STALE")
        self.assertEqual(plans[0]["status"], "blocked")

    def test_fresh_snapshot_passes_staleness_gate(self):
        fresh_ms = int(time.time() * 1000) - 30_000
        plans = generate_account_execution_plans(
            self.account, self.run_config, self.strategy,
            self.snapshot(fresh_ms), snapshot_max_age_seconds=600,
        )
        self.assertNotEqual(plans[0]["event_type"], "SYNC_STALE")


if __name__ == "__main__":
    unittest.main()
