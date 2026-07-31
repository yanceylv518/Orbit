import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.live_risk import (
    live_small_drawdown_projection,
    live_small_drawdown_stop_reason,
)


class LiveRiskTests(unittest.TestCase):
    def test_projection_and_stop_reason_share_the_frozen_thirty_percent_boundary(self):
        observations = [
            {"live_equity_usdt": 500, "paper_equity": 1.0},
            {"live_equity_usdt": 350, "paper_equity": 0.8},
        ]

        projection = live_small_drawdown_projection(observations)

        self.assertEqual(projection["live_drawdown_pct"], 30.0)
        self.assertEqual(projection["paper_drawdown_pct"], 20.0)
        self.assertEqual(projection["stop_threshold_pct"], 30.0)
        self.assertEqual(
            live_small_drawdown_stop_reason(observations),
            "LIVE_DRAWDOWN_30.0000_PCT",
        )

    def test_missing_baseline_is_not_presented_as_zero_risk(self):
        projection = live_small_drawdown_projection([])
        self.assertIsNone(projection["live_drawdown_pct"])
        self.assertIsNone(projection["paper_drawdown_pct"])
        self.assertEqual(
            live_small_drawdown_stop_reason([]),
            "EQUITY_BASELINE_MISSING",
        )


if __name__ == "__main__":
    unittest.main()
