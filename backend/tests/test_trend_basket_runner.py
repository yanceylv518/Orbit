import math
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import FundingPoint, MarketCandle
from orbit.domain.calibration.trend_basket import trend_basket_report
from orbit.domain.strategy.trend_basket_runner import (
    FrozenTrendBasketRunner,
    TB4_SPEC,
)


class FrozenTrendBasketRunnerTest(unittest.TestCase):
    def setUp(self):
        length = TB4_SPEC.warmup_ticks + TB4_SPEC.rebalance_ticks * 3 + 8
        self.times = [index * TB4_SPEC.interval_ms for index in range(length)]
        self.markets = {}
        for market_index, symbol in enumerate(TB4_SPEC.symbols):
            prices = [100.0 + market_index]
            for index in range(1, length):
                trend = 0.0015 if market_index % 2 == 0 else -0.0012
                wave = 0.0008 * math.sin((index + market_index) / 11)
                prices.append(prices[-1] * (1 + trend + wave))
            candles = [
                MarketCandle(time_ms, price, price, price, price)
                for time_ms, price in zip(self.times, prices)
            ]
            funding = [
                FundingPoint(time_ms, (market_index - 5) * 0.000001)
                for time_ms in range(0, self.times[-1] + 1, 8 * 3_600_000)
            ]
            self.markets[symbol] = (candles, funding)

    def test_replay_matches_offline_estimator_at_every_period_and_rebalance(self):
        evaluation_start = self.times[TB4_SPEC.warmup_ticks + 1]
        offline = trend_basket_report(
            self.markets,
            momentum_lookback=TB4_SPEC.momentum_lookbacks[0],
            momentum_lookbacks=TB4_SPEC.momentum_lookbacks,
            volatility_lookback=TB4_SPEC.volatility_lookback,
            rebalance_ticks=TB4_SPEC.rebalance_ticks,
            interval_ms=TB4_SPEC.interval_ms,
            target_portfolio_vol=TB4_SPEC.target_portfolio_vol,
            gross_cap=TB4_SPEC.gross_cap,
            roundtrip_cost_pct=TB4_SPEC.roundtrip_cost_pct,
            evaluation_start_ms=evaluation_start,
            evaluation_end_ms=self.times[-1],
            min_markets=len(TB4_SPEC.symbols),
            min_span_days=1,
            min_funding_coverage=0.99,
        )

        runner = FrozenTrendBasketRunner()
        funding_by_symbol = {
            symbol: {point.funding_time_ms: point.funding_rate for point in history[1]}
            for symbol, history in self.markets.items()
        }
        for index, time_ms in enumerate(self.times):
            closes = {
                symbol: history[0][index].close
                for symbol, history in self.markets.items()
            }
            previous_time = self.times[index - 1] if index else -1
            funding = {
                symbol: sum(
                    rate for event_time, rate in points.items()
                    if previous_time < event_time <= time_ms
                )
                for symbol, points in funding_by_symbol.items()
            }
            runner.on_close(
                time_ms,
                closes,
                funding,
                record_return=evaluation_start <= time_ms,
                allow_signal=(
                    index + 2 < len(self.times)
                    and evaluation_start <= self.times[index + 1]
                ),
            )
        runner.finalize_replay()

        self.assertEqual(len(runner.net_returns_pct), len(offline["net_returns_pct"]))
        for actual, expected in zip(runner.net_returns_pct, offline["net_returns_pct"]):
            self.assertAlmostEqual(actual, expected, places=12)
        self.assertEqual(len(runner.rebalances), len(offline["rebalances"]))
        for actual, expected in zip(runner.rebalances, offline["rebalances"]):
            self.assertEqual(actual["signal_time_ms"], expected["signal_time_ms"])
            self.assertEqual(actual["execution_time_ms"], expected["execution_time_ms"])
            self.assertAlmostEqual(actual["turnover"], expected["turnover"], places=12)
            self.assertAlmostEqual(actual["cost_pct"], expected["cost_pct"], places=12)
            for symbol in TB4_SPEC.symbols:
                self.assertAlmostEqual(
                    actual["target_weights"][symbol],
                    expected["target_weights"][symbol],
                    places=12,
                )

    def test_rejects_missing_market_and_non_contiguous_close(self):
        runner = FrozenTrendBasketRunner()
        first = {symbol: 100.0 for symbol in TB4_SPEC.symbols}
        runner.on_close(0, first)
        with self.assertRaisesRegex(ValueError, "exact frozen"):
            runner.on_close(TB4_SPEC.interval_ms, {"BTCUSDT": 101.0})
        with self.assertRaisesRegex(ValueError, "contiguous"):
            runner.on_close(TB4_SPEC.interval_ms * 2, first)


if __name__ == "__main__":
    unittest.main()
