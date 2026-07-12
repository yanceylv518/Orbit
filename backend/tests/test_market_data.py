import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from decimal import Decimal

from orbit.application.market_data import MarketFeedService
from orbit.application.symbol_states import SymbolStateService
from orbit.config import load_config
from orbit.domain.strategy.engine import EventEngine
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository


class FakeFeed:
    def __init__(self):
        self.klines = {}
        self.calls = []

    def closed_klines(self, symbol, interval, limit):
        self.calls.append((symbol, interval, limit))
        rows = self.klines.get(symbol)
        if isinstance(rows, Exception):
            raise rows
        return rows or []


def kline(close_time, close):
    return {
        "open_time": close_time - 60_000,
        "close_time": close_time,
        "open": close,
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": 1.0,
    }


class MarketFeedServiceTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.engine = EventEngine(self.strategy)
        self.states = InMemorySymbolStateRepository({})
        self.accounts = ConfigAccountRepository({
            "users": [],
            "exchange_accounts": [{"id": "acct_a"}],
        })
        self.run_configs = InMemoryRunConfigRepository([
            {**cfg["account_run_configs"][0], "account_id": "acct_a", "enabled": True, "symbols": ["BTCUSDT"]},
        ], {})
        self.snapshots = InMemoryAccountSnapshotRepository({
            "acct_a": {"status": "synced", "position_mode": {"hedge_mode_ok": True}},
        })
        self.symbol_states = SymbolStateService(
            self.strategy, self.engine, self.states,
            self.accounts, self.run_configs, self.snapshots,
        )
        self.feed = FakeFeed()
        self.runtime_state = {}
        self.service = MarketFeedService(
            self.feed, self.accounts, self.run_configs, self.snapshots,
            self.states, self.symbol_states, self.runtime_state,
            interval="1m", limit=3,
        )
        # 初始生命周期状态（同步创建后的形态）
        state = self.engine.initialize_symbol("BTCUSDT", Decimal("60000"), Decimal("100"))
        state["account_id"] = "acct_a"
        state["exchange_account_id"] = "acct_a"
        self.states.replace_all({"acct_a::BTCUSDT": state})

    def test_apply_advances_lifecycle_per_closed_kline(self):
        klines = {"BTCUSDT": [kline(1_000_000, 60000.0), kline(1_060_000, 60300.0)]}
        result = self.service.apply(klines)
        state = self.states.all()["acct_a::BTCUSDT"]
        self.assertEqual(result["ticks"], 2)
        self.assertEqual(result["changed_account_ids"], {"acct_a"})
        self.assertEqual(int(state["tick_count"]), 2)
        self.assertEqual(state["last_price"], "60300.0")
        self.assertEqual(state["last_kline_close_time"], 1_060_000)

    def test_apply_is_idempotent_per_kline(self):
        klines = {"BTCUSDT": [kline(1_000_000, 60000.0)]}
        first = self.service.apply(klines)
        second = self.service.apply(klines)
        self.assertEqual(first["ticks"], 1)
        self.assertEqual(second["ticks"], 0)
        self.assertEqual(int(self.states.all()["acct_a::BTCUSDT"]["tick_count"]), 1)

    def test_poll_records_error_per_symbol_without_raising(self):
        self.feed.klines["BTCUSDT"] = RuntimeError("boom")
        result = self.service.poll()
        self.assertEqual(result, {})
        self.assertIn("BTCUSDT", self.service.status["last_error"])

    def test_poll_skips_unsynced_accounts(self):
        self.snapshots.save("acct_a", {"status": "error"})
        self.feed.klines["BTCUSDT"] = [kline(1_000_000, 60000.0)]
        result = self.service.poll()
        self.assertEqual(result, {})
        self.assertEqual(self.feed.calls, [])


if __name__ == "__main__":
    unittest.main()
