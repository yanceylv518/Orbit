import unittest
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config
from orbit.domain.strategy.exposure import decide_target_exposure, derive_anchor_price


class TargetExposureTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.base_price = Decimal("100")
        self.base_qty = Decimal("1")

    def decide(self, price, long_qty="1", short_qty="1", strategy=None):
        return decide_target_exposure(
            price=Decimal(str(price)),
            base_price=self.base_price,
            base_qty=self.base_qty,
            long_qty=Decimal(str(long_qty)),
            short_qty=Decimal(str(short_qty)),
            strategy=strategy or self.strategy,
        )

    def test_up_move_creates_inverse_short_skew(self):
        decision = self.decide("102")

        self.assertEqual(decision.event_type, "PROFIT_TRANSFER_UP")
        self.assertEqual(decision.lifecycle_state, "SKEWED_SHORT")
        self.assertLess(decision.target_net_qty, 0)
        self.assertLess(decision.delta_qty, 0)

    def test_down_move_creates_inverse_long_skew(self):
        decision = self.decide("98")

        self.assertEqual(decision.event_type, "PROFIT_TRANSFER_DOWN")
        self.assertEqual(decision.lifecycle_state, "SKEWED_LONG")
        self.assertGreater(decision.target_net_qty, 0)
        self.assertGreater(decision.delta_qty, 0)

    def test_trend_band_flips_exposure_to_trend_direction(self):
        decision = self.decide("105")

        self.assertEqual(decision.event_type, "LOSS_SIDE_REDUCTION_UP")
        self.assertEqual(decision.lifecycle_state, "TREND_UP")
        self.assertGreater(decision.target_net_qty, 0)

    def test_neutralization_geometry_only_removes_counter_trend_skew(self):
        strategy = deepcopy(self.strategy)
        strategy["strategy"]["events"]["loss_side_reduction"]["sizing"][
            "neutralize_counter_trend_skew_only"
        ] = True

        counter_trend = self.decide("105", long_qty="0.7", short_qty="1.0", strategy=strategy)
        neutral = self.decide("105", strategy=strategy)
        aligned = self.decide("105", long_qty="1.0", short_qty="0.7", strategy=strategy)

        self.assertEqual(counter_trend.event_type, "LOSS_SIDE_REDUCTION_UP")
        self.assertEqual(counter_trend.target_net_qty, 0)
        self.assertEqual(counter_trend.delta_qty, Decimal("0.30000000"))
        self.assertIsNone(neutral.event_type)
        self.assertIsNone(aligned.event_type)
        self.assertEqual(aligned.target_net_qty, aligned.current_net_qty)

    def test_recovery_returns_existing_skew_to_zero(self):
        decision = self.decide("100.2", long_qty="0.7", short_qty="1.0")

        self.assertEqual(decision.event_type, "POSITION_RECOVERY_UP")
        self.assertEqual(decision.lifecycle_state, "REANCHORING")
        self.assertEqual(decision.target_net_qty, 0)
        self.assertGreater(decision.delta_qty, 0)

    def test_rebuild_restores_balanced_legs_to_base(self):
        decision = self.decide("100.2", long_qty="0.7", short_qty="0.7")

        self.assertEqual(decision.event_type, "POSITION_REBUILD")
        self.assertEqual(decision.lifecycle_state, "REANCHORING")
        self.assertEqual(decision.target_net_qty, 0)
        self.assertEqual(decision.delta_qty, 0)
        self.assertEqual(decision.target_long_qty, Decimal("1.00000000"))
        self.assertEqual(decision.target_short_qty, Decimal("1.00000000"))

    def test_anchor_price_uses_both_legs_when_available(self):
        anchor = derive_anchor_price(Decimal("60000"), Decimal("62100"), Decimal("62000"))

        self.assertEqual(anchor, Decimal("61050"))


if __name__ == "__main__":
    unittest.main()
