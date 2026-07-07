import unittest
from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddg.config import load_config
from ddg.engine import EventEngine


class EventEngineTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.engine = EventEngine(self.strategy)
        self.state = self.engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))

    def test_profit_transfer_before_trend_confirm(self):
        state, events, risks = self.engine.on_tick(self.state, Decimal("61500"))
        self.assertFalse(risks)
        self.assertTrue(events)
        self.assertEqual(events[0]["event_type"], "PROFIT_TRANSFER_UP")
        self.assertTrue(any(t["action"] == "REDUCE_LONG" for t in events[0]["trades"]))
        self.assertTrue(any(t["action"] == "ADD_SHORT" for t in events[0]["trades"]))

    def test_loss_side_reduction_after_trend_confirm(self):
        state, events, risks = self.engine.on_tick(self.state, Decimal("62500"))
        self.assertTrue(events)
        self.assertEqual(events[0]["event_type"], "LOSS_SIDE_REDUCTION_UP")
        self.assertTrue(any(t["action"] == "REDUCE_SHORT" for t in events[0]["trades"]))


if __name__ == "__main__":
    unittest.main()
