import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.metrics import MetricHistoryService
from orbit.application.strategy_config import StrategyEventConfigService
from orbit.config import load_config
from orbit.infrastructure.persistence.metrics import InMemoryMetricHistoryRepository
from orbit.infrastructure.persistence.strategy_runtime import InMemoryStrategyRuntimeRepository


class StrategyConfigAndMetricServiceTest(unittest.TestCase):
    def test_event_config_updates_known_values_and_returns_engine(self):
        strategy = load_config(str(ROOT / "config" / "config.sample.json"))["strategy_instances"][0]
        runtime = InMemoryStrategyRuntimeRepository(strategy, {"running": False})
        service = StrategyEventConfigService(runtime)

        result = service.update(
            {"profit_transfer": {"guard": {"cooldown_ticks": -2}}, "unknown": 1},
            actor="admin_001",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["event_config"]["profit_transfer"]["guard"]["cooldown_ticks"], 0)
        self.assertNotIn("unknown", result["event_config"])
        self.assertEqual(result["_audit"]["action_type"], "UPDATE_EVENT_CONFIG")

    def test_metric_service_records_total_and_symbol_points(self):
        repository = InMemoryMetricHistoryRepository([], {})
        service = MetricHistoryService(repository)
        symbol = {
            "symbol": "BTCUSDT", "equity": 100, "long_qty": 1, "short_qty": 0.5,
            "price": 10, "net_exposure": 5, "gross_exposure": 15, "fee_total": 1,
            "profit_transfer_count": 1, "loss_side_reduce_count": 2, "recovery_count": 3,
        }

        service.record(
            tick=7,
            symbols=[symbol],
            totals={"total_equity": 100, "total_fees": 1, "total_slippage": 0.5},
        )

        self.assertEqual(repository.all()[0]["tick"], 7)
        self.assertEqual(repository.by_symbol()["BTCUSDT"][0]["long_notional"], 10)


if __name__ == "__main__":
    unittest.main()
