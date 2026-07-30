from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.trend_execution_checklist import TrendExecutionChecklistProjector
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC


def weights(**overrides):
    result = {symbol: 0.0 for symbol in TB4_SPEC.symbols}
    result.update(overrides)
    return result


class FakeRunner:
    def __init__(self):
        close_time = int(datetime(2026, 7, 30, tzinfo=timezone.utc).timestamp() * 1000)
        self.times = [close_time]
        self.closes = {symbol: [100.0] for symbol in TB4_SPEC.symbols}
        self.closes["BTCUSDT"] = [100_000.0]
        self.closes["ETHUSDT"] = [2_000.0]
        self.rebalances = [
            {
                "signal_time_ms": close_time - TB4_SPEC.interval_ms,
                "execution_time_ms": close_time - 7 * 86_400_000,
                "target_weights": weights(BTCUSDT=-0.1),
            },
            {
                "signal_time_ms": close_time - TB4_SPEC.interval_ms,
                "execution_time_ms": close_time,
                "target_weights": weights(BTCUSDT=0.2, ETHUSDT=-0.1, BNBUSDT=0.005),
            },
        ]


class TrendExecutionChecklistProjectorTest(unittest.TestCase):
    def test_projects_direction_quantity_flip_and_minimums_without_mutation(self):
        runner = FakeRunner()
        before = deepcopy(runner.__dict__)
        projector = TrendExecutionChecklistProjector(live_capital_usdt=500)

        first = projector.project(runner)
        second = projector.project(runner)

        self.assertEqual(first, second)
        self.assertEqual(runner.__dict__, before)
        self.assertEqual(first["status"], "READY")
        rows = {row["symbol"]: row for row in first["rows"]}
        self.assertEqual(rows["BTCUSDT"]["direction"], "LONG")
        self.assertEqual(rows["BTCUSDT"]["target_quantity"], 0.001)
        self.assertEqual(rows["BTCUSDT"]["notional_change_usdt"], 150.0)
        self.assertEqual(rows["ETHUSDT"]["direction"], "SHORT")
        self.assertEqual(rows["ETHUSDT"]["target_quantity"], 0.025)
        self.assertEqual(rows["BNBUSDT"]["status"], "BELOW_MIN_NOTIONAL")
        self.assertEqual(rows["BNBUSDT"]["target_quantity"], 0.0)
        self.assertEqual(rows["SOLUSDT"]["status"], "FLAT")
        self.assertEqual(first["summary"]["executable_symbols"], 2)
        self.assertEqual(first["summary"]["below_minimum_symbols"], 1)
        self.assertAlmostEqual(first["summary"]["target_gross_notional_usdt"], 152.5)
        self.assertAlmostEqual(first["summary"]["executable_gross_notional_usdt"], 150.0)
        self.assertAlmostEqual(
            first["summary"]["executable_notional_ratio"], 150.0 / 152.5,
        )

    def test_capital_changes_only_the_projection_and_can_cross_minimum(self):
        runner = FakeRunner()
        small = TrendExecutionChecklistProjector(live_capital_usdt=500).project(runner)
        large = TrendExecutionChecklistProjector(live_capital_usdt=1000).project(runner)

        small_bnb = next(row for row in small["rows"] if row["symbol"] == "BNBUSDT")
        large_bnb = next(row for row in large["rows"] if row["symbol"] == "BNBUSDT")
        self.assertEqual(small_bnb["status"], "BELOW_MIN_NOTIONAL")
        self.assertEqual(large_bnb["status"], "EXECUTABLE")
        self.assertEqual(large_bnb["target_quantity"], 0.05)
        self.assertEqual(runner.rebalances[-1]["target_weights"]["BNBUSDT"], 0.005)

    def test_reports_not_started_and_awaiting_first_rebalance(self):
        projector = TrendExecutionChecklistProjector()
        runner = FakeRunner()
        runner.times = []
        runner.rebalances = []
        self.assertEqual(projector.project(runner)["status"], "NOT_AVAILABLE")

        runner.times = [1]
        runner.rebalances = []
        self.assertEqual(projector.project(runner)["status"], "AWAITING_FIRST_REBALANCE")


if __name__ == "__main__":
    unittest.main()
