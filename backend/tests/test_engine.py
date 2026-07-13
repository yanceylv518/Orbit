import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine


class EventEngineTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.strategy["strategy"]["regime_gate"]["enabled"] = False
        self.engine = EventEngine(self.strategy)
        self.state = self.engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))

    def test_profit_transfer_before_trend_confirm(self):
        state, events, risks = self.engine.on_tick(self.state, Decimal("61500"))
        self.assertFalse(risks)
        self.assertTrue(events)
        self.assertEqual(events[0]["event_type"], "PROFIT_TRANSFER_UP")
        self.assertEqual(events[0]["trigger"]["exposure_model"], "net_exposure_v1")
        self.assertEqual(state["state"], "SKEWED_SHORT")
        self.assertLess(Decimal(state["long_qty"]) - Decimal(state["short_qty"]), 0)
        self.assertTrue(any(t["action"] == "REDUCE_LONG" for t in events[0]["trades"]))
        self.assertTrue(any(t["action"] == "ADD_SHORT" for t in events[0]["trades"]))

    def test_regime_block_is_recorded_without_mutating_positions_or_pnl(self):
        self.strategy["strategy"]["regime_gate"]["enabled"] = True
        engine = EventEngine(self.strategy)
        state = engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))
        state.update({
            "regime": "TRENDING",
            "regime_raw": "TRENDING",
            "regime_stable": "TRENDING",
            "regime_price_history": [57000 + index * 100 for index in range(30)],
            "regime_features": {
                "sample_count": 30,
                "efficiency_ratio": 0.8,
                "return_autocorrelation": 0.4,
                "volatility_pct": 0.2,
            },
        })
        before = {key: state[key] for key in ("long_qty", "short_qty", "realized_pnl")}

        updated, events, risks = engine.on_tick(state, Decimal("61500"))

        self.assertFalse(events)
        self.assertEqual(len(risks), 1)
        blocked = risks[0]
        self.assertEqual(blocked["risk_type"], "REGIME_TRENDING_BLOCKED")
        self.assertEqual(blocked["action_taken"], "BLOCKED_NO_TRADE")
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["trades"], [])
        self.assertEqual(blocked["trigger"]["block_source"], "regime_gate")
        self.assertEqual(blocked["trigger"]["regime"], "TRENDING")
        self.assertIn("efficiency_ratio", blocked["trigger"])
        self.assertEqual(
            {key: updated[key] for key in before},
            before,
        )

        _, repeated_risks = engine.execute_paper_tick(updated, Decimal("61500"))
        self.assertEqual(repeated_risks, [])
        self.assertEqual(updated["last_block_code"], "REGIME_TRENDING_BLOCKED")

        updated["regime"] = "RANGE"
        engine.execute_paper_tick(updated, Decimal("60000"))
        self.assertIsNone(updated["last_block_code"])
        updated["regime"] = "TRENDING"
        _, reentered_risks = engine.execute_paper_tick(updated, Decimal("61500"))
        self.assertEqual(len(reentered_risks), 1)
        self.assertEqual(reentered_risks[0]["risk_type"], "REGIME_TRENDING_BLOCKED")

    def test_loss_side_reduction_after_trend_confirm(self):
        # trend_entry_confirm_ticks=2：第一根确认 K 线只计数不动作
        state, events, risks = self.engine.on_tick(self.state, Decimal("62500"))
        self.assertFalse(events)
        self.assertEqual(state["trend_entry_candidate_count"], 1)
        state, events, risks = self.engine.on_tick(state, Decimal("62550"))
        self.assertTrue(events)
        self.assertEqual(events[0]["event_type"], "LOSS_SIDE_REDUCTION_UP")
        self.assertEqual(state["state"], "TREND_UP")
        self.assertGreater(Decimal(state["long_qty"]) - Decimal(state["short_qty"]), 0)
        self.assertTrue(any(t["action"] == "REDUCE_SHORT" for t in events[0]["trades"]))

    def test_recovery_reanchors_after_skew_returns_to_band(self):
        skewed, events, risks = self.engine.on_tick(self.state, Decimal("61500"))
        self.assertTrue(events)

        recovered, recovery_events, risks = self.engine.on_tick(skewed, Decimal("60050"))

        self.assertFalse(risks)
        self.assertTrue(recovery_events)
        self.assertEqual(recovery_events[0]["event_type"], "POSITION_RECOVERY_UP")
        self.assertEqual(recovered["state"], "BALANCED")
        self.assertEqual(Decimal(recovered["base_price"]), Decimal("60050"))
        self.assertEqual(recovered["profit_transfer_count_in_trend"], 0)
        self.assertEqual(recovered["loss_side_reduce_count_in_trend"], 0)
        self.assertEqual(recovered["recovery_count_in_trend"], 0)

    def test_rebuild_adds_both_legs_when_balanced_position_is_below_base(self):
        state = dict(self.state)
        state["long_qty"] = "0.00050000"
        state["short_qty"] = "0.00050000"

        rebuilt, events, risks = self.engine.on_tick(state, Decimal("60050"))

        self.assertFalse(risks)
        self.assertTrue(events)
        self.assertEqual(events[0]["event_type"], "POSITION_REBUILD")
        self.assertEqual(rebuilt["state"], "BALANCED")
        self.assertTrue(any(t["action"] == "ADD_LONG" for t in events[0]["trades"]))
        self.assertTrue(any(t["action"] == "ADD_SHORT" for t in events[0]["trades"]))
        self.assertGreater(Decimal(rebuilt["long_qty"]), Decimal("0.00050000"))
        self.assertGreater(Decimal(rebuilt["short_qty"]), Decimal("0.00050000"))

    def test_trend_exit_requires_sustained_pullback_before_recovery(self):
        state = dict(self.state)
        state.update({
            "state": "TREND_UP",
            "high_since_base": "62500",
            "trend_extreme_price": "62500",
            "long_qty": "0.00066666",
            "short_qty": "0.00030000",
        })

        first_tick, first_events, risks = self.engine.on_tick(state, Decimal("60700"))
        self.assertEqual(len(risks), 1)
        self.assertEqual(risks[0]["risk_type"], "TREND_EXIT_NOT_CONFIRMED")
        self.assertEqual(risks[0]["action_taken"], "BLOCKED_NO_TRADE")
        self.assertEqual(risks[0]["trigger"]["block_source"], "event_rule")
        self.assertFalse(first_events)
        self.assertEqual(first_tick["state"], "TREND_UP")
        self.assertEqual(first_tick["trend_exit_candidate_count"], 1)

        second_tick, second_events, risks = self.engine.on_tick(first_tick, Decimal("60700"))
        self.assertFalse(risks)
        self.assertTrue(second_events)
        self.assertEqual(second_events[0]["event_type"], "POSITION_RECOVERY_DOWN")
        self.assertEqual(second_tick["state"], "REANCHORING")

    def test_gross_limit_enters_only_reduce_and_blocks_add_leg(self):
        state = self.engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("40"))

        state, events, risks = self.engine.on_tick(state, Decimal("61500"))

        self.assertTrue(risks)
        self.assertEqual(risks[0]["risk_type"], "MAX_GROSS_EXPOSURE")
        self.assertTrue(events)
        self.assertTrue(any(t["action"] == "REDUCE_LONG" for t in events[0]["trades"]))
        self.assertFalse(any(t["action"] == "ADD_SHORT" for t in events[0]["trades"]))
        self.assertTrue(any(item["action"] == "ADD_SHORT" for item in events[0]["blocked_actions"]))

    def test_symbol_drawdown_stop_unwinds_and_becomes_absorbing(self):
        state = self.engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))
        state["realized_pnl"] = "-11"

        stopped, events, risks = self.engine.on_tick(state, Decimal("60000"))

        self.assertFalse(events)
        self.assertTrue(risks)
        self.assertEqual(risks[0]["risk_type"], "MAX_SYMBOL_DRAWDOWN")
        self.assertEqual(risks[0]["action_taken"], "STOPPED_UNWIND")
        self.assertEqual(stopped["state"], "STOPPED")
        self.assertEqual(Decimal(stopped["long_qty"]), Decimal("0E-8"))
        self.assertEqual(Decimal(stopped["short_qty"]), Decimal("0E-8"))
        self.assertEqual(len(risks[0]["trades"]), 2)


if __name__ == "__main__":
    unittest.main()
