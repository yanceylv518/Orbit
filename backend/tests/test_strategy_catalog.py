import unittest
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.strategy_catalog import (
    TB4_DEFINITION,
    TB4_STRATEGY_ID,
    StrategyCatalogService,
    tb4_spec_payload,
)
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC


class StrategyCatalogTests(unittest.TestCase):
    def test_serialized_spec_matches_frozen_runner_field_for_field(self):
        self.assertEqual(tb4_spec_payload(), {
            "symbols": list(TB4_SPEC.symbols),
            "interval_ms": TB4_SPEC.interval_ms,
            "momentum_lookbacks": list(TB4_SPEC.momentum_lookbacks),
            "volatility_lookback": TB4_SPEC.volatility_lookback,
            "rebalance_ticks": TB4_SPEC.rebalance_ticks,
            "target_portfolio_vol": TB4_SPEC.target_portfolio_vol,
            "gross_cap": TB4_SPEC.gross_cap,
            "roundtrip_cost_pct": TB4_SPEC.roundtrip_cost_pct,
        })

    def test_live_pilot_keeps_parallel_paper_forward_progress(self):
        service = StrategyCatalogService(
            lambda: {
                "status": "RUNNING",
                "elapsed_days": 21,
                "minimum_forward_days": 365,
                "progress_ratio": 21 / 365,
                "verdict": None,
            },
            lambda: {
                "status": "ENABLED",
                "account_id": "secret-account",
                "execution_epoch": "secret-epoch",
            },
            live_capital_usdt=500,
            live_configured=True,
        )

        strategy = service.strategy(TB4_STRATEGY_ID)
        lifecycle = strategy["lifecycle"]

        self.assertEqual(lifecycle["primary"], "LIVE_PILOT")
        self.assertEqual(
            lifecycle["phases"],
            ["BACKTEST_CONFIRMED", "PAPER_FORWARD", "LIVE_PILOT"],
        )
        self.assertEqual(lifecycle["paper_forward"]["elapsed_days"], 21)
        self.assertEqual(lifecycle["live_pilot"]["capital_usdt"], 500)
        self.assertNotIn("account_id", str(strategy))
        self.assertNotIn("execution_epoch", str(strategy))

    def test_unknown_strategy_is_not_synthesized(self):
        service = StrategyCatalogService(lambda: {}, lambda: {}, live_capital_usdt=500)
        with self.assertRaises(KeyError):
            service.strategy("missing")

    def test_public_strategy_name_contains_no_internal_code(self):
        self.assertEqual(TB4_DEFINITION.name, "多周期趋势")
        self.assertNotIn("TB4", TB4_DEFINITION.name)


if __name__ == "__main__":
    unittest.main()
