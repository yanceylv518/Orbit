import unittest
from decimal import Decimal
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.symbol_states import SymbolStateService
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository
from orbit.config import load_config
from orbit.domain.planning.plans import group_positions
from orbit.domain.strategy.engine import EventEngine


class SymbolStateServiceTest(unittest.TestCase):
    def setUp(self):
        cfg = load_config(str(ROOT / "config" / "config.sample.json"))
        self.strategy = cfg["strategy_instances"][0]
        self.engine = EventEngine(self.strategy)
        self.repository = InMemorySymbolStateRepository({})
        self.run_config = cfg["account_run_configs"][0]
        self.accounts = ConfigAccountRepository({
            "users": [],
            "exchange_accounts": [{"id": "binance_dry_run_001"}],
        })
        self.run_configs = InMemoryRunConfigRepository([self.run_config], {})
        self.snapshots = InMemoryAccountSnapshotRepository({})
        self.service = SymbolStateService(
            self.strategy,
            self.engine,
            self.repository,
            self.accounts,
            self.run_configs,
            self.snapshots,
        )

    def test_refresh_keeps_lifecycle_anchor_and_updates_real_position(self):
        existing = {
            "BTCUSDT": {
                "symbol": "BTCUSDT",
                "state": "TREND_UP",
                "base_price": "60000",
                "base_qty": "0.00066666",
                "high_since_base": "62500",
                "low_since_base": "60000",
                "trend_extreme_price": "62500",
                "last_price": "62500",
                "long_qty": "0.00066666",
                "short_qty": "0.00030000",
                "long_entry_price": "60000",
                "short_entry_price": "62500",
                "budget_usdt": "100",
                "realized_pnl": "0",
                "long_unrealized_pnl": "0",
                "short_unrealized_pnl": "0",
                "fee_total": "0",
                "slippage_total": "0",
                "funding_total": "0",
                "trend_exit_candidate_count": 0,
                "tick_count": 1,
            }
        }
        positions = group_positions([
            {
                "symbol": "BTCUSDT",
                "position_side": "LONG",
                "position_amt": 0.00070000,
                "entry_price": 60000,
                "mark_price": 60700,
                "unrealized_profit": 0.49,
                "notional": 42.49,
            },
            {
                "symbol": "BTCUSDT",
                "position_side": "SHORT",
                "position_amt": -0.00030000,
                "entry_price": 62500,
                "mark_price": 60700,
                "unrealized_profit": 0.54,
                "notional": -18.21,
            },
        ], ["BTCUSDT"])

        state = self.service.plan_symbol_state_from_snapshot(
            account_id="binance_dry_run_001",
            run_config=self.run_config,
            symbol="BTCUSDT",
            sides=positions["BTCUSDT"],
            existing_state=existing["BTCUSDT"],
        )

        self.assertEqual(state["base_price"], "60000")
        self.assertEqual(state["state"], "TREND_UP")
        self.assertEqual(state["long_qty"], "0.00070000")
        self.assertEqual(state["short_qty"], "0.00030000")
        self.assertEqual(state["trend_exit_candidate_count"], 1)
        self.assertEqual(state["account_id"], "binance_dry_run_001")

    def test_refresh_plan_symbol_states_writes_repository(self):
        snapshot = {
            "status": "synced",
            "position_mode": {"hedge_mode_ok": True},
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "position_side": "LONG",
                    "position_amt": 0.001,
                    "entry_price": 60000,
                    "mark_price": 60900,
                    "unrealized_profit": 0.9,
                    "notional": 60.9,
                },
                {
                    "symbol": "BTCUSDT",
                    "position_side": "SHORT",
                    "position_amt": -0.001,
                    "entry_price": 60000,
                    "mark_price": 60900,
                    "unrealized_profit": -0.9,
                    "notional": -60.9,
                },
            ],
        }

        self.snapshots.save("binance_dry_run_001", snapshot)
        self.service.refresh_plan_symbol_states(account_ids={"binance_dry_run_001"})

        states = self.repository.all()
        self.assertIn("BTCUSDT", states)
        self.assertEqual(states["BTCUSDT"]["source"], "binance_plan_state")
        self.assertEqual(states["BTCUSDT"]["last_price"], "60900")


if __name__ == "__main__":
    unittest.main()
