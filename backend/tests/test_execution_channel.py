import time
import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.order_execution import OrderExecutionService
from orbit.application.paper_execution import PaperExecutionService
from orbit.application.permissions import PermissionPolicy
from orbit.application.runtime_events import RuntimeEventService
from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.event_history import InMemoryEventHistoryRepository
from orbit.infrastructure.persistence.execution_plans import InMemoryExecutionPlanRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository


ADMIN = {"id": "admin_001", "role": "admin", "status": "active"}


class PaperExecutionTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.engine = EventEngine(self.strategy)
        state = self.engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))
        state["account_id"] = "acct_paper"
        # 价格已被行情循环推到 +2%（偏斜带内），等待 paper 执行
        state["last_price"] = "61200"
        state["high_since_base"] = "61200"
        state["tick_count"] = 3
        state["regime"] = "RANGE"
        state["regime_stable"] = "RANGE"
        self.states = InMemorySymbolStateRepository({"acct_paper::BTCUSDT": state})
        self.run_configs = InMemoryRunConfigRepository([
            {"account_id": "acct_paper", "enabled": True, "mode": "paper"},
        ], {})
        self.events = InMemoryEventHistoryRepository([], [], [])
        self.service = PaperExecutionService(
            self.engine, self.run_configs, self.states,
            RuntimeEventService(self.events, self.strategy["id"]),
        )

    def test_paper_tick_executes_virtual_trades_and_records_events(self):
        result = self.service.on_market_tick({"acct_paper"})
        self.assertGreaterEqual(result["events"], 1)
        state = self.states.all()["acct_paper::BTCUSDT"]
        # 建立了逆势偏斜：净敞口变负（涨后净空）
        delta = Decimal(state["long_qty"]) - Decimal(state["short_qty"])
        self.assertLess(delta, 0)
        recorded = self.events.strategy_events()
        self.assertTrue(recorded)
        self.assertEqual(recorded[0]["exchange_account_id"], "acct_paper")

    def test_non_paper_accounts_are_untouched(self):
        self.run_configs.replace_all([
            {"account_id": "acct_paper", "enabled": True, "mode": "plan_only"},
        ])
        result = self.service.on_market_tick({"acct_paper"})
        self.assertEqual(result["events"], 0)
        state = self.states.all()["acct_paper::BTCUSDT"]
        self.assertEqual(Decimal(state["long_qty"]), Decimal(state["short_qty"]))


class FakeGateway:
    def __init__(self):
        self.orders = []
        self.fail_on = None

    def place_order(self, params):
        if self.fail_on and params["side"] == self.fail_on:
            raise RuntimeError("exchange rejected")
        self.orders.append(params)
        return {"orderId": len(self.orders), "status": "FILLED"}


class OrderExecutionGateTest(unittest.TestCase):
    def setUp(self):
        self.account = {
            "id": "acct_live",
            "user_id": "user_001",
            "dry_run": False,
            "status": "active",
        }
        self.plan = {
            "id": "plan_live_001",
            "account_id": "acct_live",
            "symbol": "BTCUSDT",
            "status": "planned",
            "expires_at_ms": int(time.time() * 1000) + 60_000,
            "manual_review": {"status": "confirmed"},
            "actions": [
                {"action": "REDUCE_SHORT", "side": "BUY", "position_side": "SHORT",
                 "quantity": 0.001, "reduce_only": True, "status": "planned"},
            ],
        }
        self.accounts = ConfigAccountRepository({
            "users": [ADMIN, {"id": "user_001", "role": "user", "status": "active"}],
            "exchange_accounts": [self.account],
        })
        self.plans = InMemoryExecutionPlanRepository([self.plan])
        self.run_configs = InMemoryRunConfigRepository([
            {"account_id": "acct_live", "enabled": True, "mode": "live"},
        ], {})
        self.gateway = FakeGateway()

        class PlanServiceStub:
            max_confirm_price_drift_pct = 0.5

            def _confirm_price_drift_pct(self, plan):
                return 0.1

        self.plan_service = PlanServiceStub()
        self.service = OrderExecutionService(
            PermissionPolicy(),
            self.accounts,
            self.run_configs,
            self.plans,
            self.plan_service,
            lambda account: self.gateway,
            live_trading_enabled=True,
            live_confirm_phrase="I UNDERSTAND LIVE TRADING",
        )

    def execute(self, **overrides):
        kwargs = {
            "plan_id": "plan_live_001",
            "actor": "admin_001",
            "actor_user": ADMIN,
            "confirm_phrase": "I UNDERSTAND LIVE TRADING",
        }
        kwargs.update(overrides)
        return self.service.execute(**kwargs)

    def test_g1_disabled_channel_refuses(self):
        self.service.live_trading_enabled = False
        result = self.execute()
        self.assertEqual(result["status"], "disabled")

    def test_g2_non_admin_refused(self):
        result = self.execute(actor="user_001", actor_user={"id": "user_001", "role": "user"})
        self.assertEqual(result["status"], "forbidden")

    def test_g3_unconfirmed_plan_refused(self):
        self.plan["manual_review"] = {}
        result = self.execute()
        self.assertEqual(result["status"], "unconfirmed")

    def test_g4_expired_plan_refused(self):
        self.plan["expires_at_ms"] = int(time.time() * 1000) - 1000
        result = self.execute()
        self.assertEqual(result["status"], "expired")

    def test_g5_mode_must_be_live(self):
        self.run_configs.replace_all([{"account_id": "acct_live", "enabled": True, "mode": "plan_only"}])
        result = self.execute()
        self.assertEqual(result["status"], "mode")

    def test_g6_dry_run_account_refused(self):
        self.account["dry_run"] = True
        result = self.execute()
        self.assertEqual(result["status"], "dry_run")

    def test_g7_wrong_phrase_refused(self):
        result = self.execute(confirm_phrase="yes")
        self.assertEqual(result["status"], "confirm_phrase")

    def test_g8_add_action_refused(self):
        self.plan["actions"].append({
            "action": "ADD_LONG", "side": "BUY", "position_side": "LONG",
            "quantity": 0.001, "reduce_only": False, "status": "planned",
        })
        result = self.execute()
        self.assertEqual(result["status"], "reduce_only_required")
        self.assertEqual(self.gateway.orders, [])

    def test_all_gates_pass_places_reduce_only_order(self):
        result = self.execute()
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "executed")
        self.assertEqual(len(self.gateway.orders), 1)
        order = self.gateway.orders[0]
        self.assertEqual(order["reduceOnly"], "true")
        self.assertEqual(order["type"], "MARKET")
        saved = self.plans.get("plan_live_001")
        self.assertEqual(saved["execution"]["status"], "executed")
        self.assertEqual(result["_audit"]["action_type"], "EXECUTE_LIVE_PLAN")

    def test_already_executed_plan_refused(self):
        self.execute()
        result = self.execute()
        self.assertEqual(result["status"], "already_executed")

    def test_gateway_failure_records_partial_or_failed(self):
        self.gateway.fail_on = "BUY"
        result = self.execute()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "failed")
        saved = self.plans.get("plan_live_001")
        self.assertEqual(saved["execution"]["status"], "failed")
        self.assertIn("exchange rejected", saved["execution"]["error"])


if __name__ == "__main__":
    unittest.main()
