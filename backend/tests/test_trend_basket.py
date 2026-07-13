import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import FundingPoint, MarketCandle
from orbit.domain.calibration.trend_basket import (
    trend_basket_data_quality,
    trend_basket_report,
    trend_performance_summary,
)


DAY_MS = 86_400_000
FUNDING_MS = 8 * 3_600_000


def price_path(returns):
    prices = [100.0]
    for value in returns:
        prices.append(prices[-1] * (1 + value))
    return prices


def candles(prices, *, interval_ms=DAY_MS):
    return [
        MarketCandle(index * interval_ms, price, price, price, price)
        for index, price in enumerate(prices)
    ]


def funding(last_time_ms, rate=0.0):
    return [
        FundingPoint(time_ms, rate)
        for time_ms in range(0, last_time_ms + 1, FUNDING_MS)
    ]


def trending_markets(length=45, funding_rate=0.0):
    up = price_path([0.02 if index % 2 else 0.005 for index in range(length - 1)])
    down = price_path([-0.02 if index % 2 else -0.005 for index in range(length - 1)])
    last_time = (length - 1) * DAY_MS
    return {
        "UP": (candles(up), funding(last_time, funding_rate)),
        "DOWN": (candles(down), funding(last_time, funding_rate)),
    }


def report(markets, **overrides):
    kwargs = {
        "momentum_lookback": 3,
        "volatility_lookback": 3,
        "rebalance_ticks": 5,
        "interval_ms": DAY_MS,
        "min_markets": 2,
        "min_span_days": 1,
        "min_funding_coverage": 0.99,
        "fold_days": 10,
    }
    kwargs.update(overrides)
    return trend_basket_report(markets, **kwargs)


class TrendBasketTest(unittest.TestCase):
    def test_signal_executes_one_bar_late(self):
        result = report(trending_markets())
        first = result["rebalances"][0]

        self.assertEqual(first["execution_time_ms"] - first["signal_time_ms"], DAY_MS)
        self.assertEqual(first["signals"]["UP"], 1)
        self.assertEqual(first["signals"]["DOWN"], -1)
        self.assertGreater(first["target_weights"]["UP"], 0)
        self.assertLess(first["target_weights"]["DOWN"], 0)

    def test_inverse_volatility_gives_quieter_market_more_weight(self):
        volatile = price_path([0.05, -0.01, 0.05, -0.01] * 12)
        quiet = price_path([0.015, 0.005, 0.015, 0.005] * 12)
        last_time = (len(volatile) - 1) * DAY_MS
        result = report({
            "VOLATILE": (candles(volatile), funding(last_time)),
            "QUIET": (candles(quiet), funding(last_time)),
        })
        weights = result["rebalances"][0]["target_weights"]

        self.assertGreater(weights["VOLATILE"], 0)
        self.assertGreater(weights["QUIET"], 0)
        self.assertLess(abs(weights["VOLATILE"]), abs(weights["QUIET"]))

    def test_cost_reduces_return_and_is_charged_on_turnover(self):
        markets = trending_markets()
        free = report(markets, roundtrip_cost_pct=0)
        costly = report(markets, roundtrip_cost_pct=0.14)

        self.assertGreater(costly["total_turnover"], 0)
        self.assertGreater(costly["total_transaction_cost_pct"], 0)
        self.assertLess(costly["total_net_return_pct"], free["total_net_return_pct"])

    def test_funding_sign_charges_longs_and_credits_shorts(self):
        result = report(trending_markets(funding_rate=0.001))

        self.assertLess(result["funding_contribution_pct"]["UP"], 0)
        self.assertGreater(result["funding_contribution_pct"]["DOWN"], 0)

    def test_nonstandard_funding_events_are_not_dropped(self):
        baseline = trending_markets()
        changed = {
            name: (market_candles, list(points))
            for name, (market_candles, points) in baseline.items()
        }
        changed["UP"][1].append(FundingPoint(5 * DAY_MS + 4 * 3_600_000, 0.01))

        without_extra = report(baseline)
        with_extra = report(changed)

        self.assertLess(
            with_extra["funding_contribution_pct"]["UP"],
            without_extra["funding_contribution_pct"]["UP"],
        )

    def test_future_prices_do_not_change_first_signal_or_target(self):
        original = trending_markets()
        altered = {}
        for name, (market_candles, points) in original.items():
            changed = list(market_candles)
            for index in range(5, len(changed)):
                price = changed[index].close * (2 if name == "DOWN" else 0.5)
                changed[index] = MarketCandle(
                    changed[index].close_time_ms, price, price, price, price,
                )
            altered[name] = (changed, points)

        first = report(original)["rebalances"][0]
        changed = report(altered)["rebalances"][0]

        self.assertEqual(first["signal_time_ms"], changed["signal_time_ms"])
        self.assertEqual(first["signals"], changed["signals"])
        self.assertEqual(first["target_weights"], changed["target_weights"])

    def test_performance_summary_reports_sharpe_drawdown_and_folds(self):
        summary = trend_performance_summary(
            [1.0, 2.0, 1.0, 2.0], periods_per_year=4, fold_periods=2,
        )

        self.assertGreater(summary["annualized_net_return_pct"], 0)
        self.assertGreater(summary["sharpe"], 0.5)
        self.assertEqual(summary["max_drawdown_pct"], 0)
        self.assertEqual(summary["profitable_folds"], 2)
        self.assertTrue(summary["performance_bar_pass"])

    def test_four_market_one_hour_data_is_non_conclusive(self):
        interval_ms = 3_600_000
        prices = price_path([0.01, -0.005] * 30)
        last_time = (len(prices) - 1) * interval_ms
        market = (candles(prices, interval_ms=interval_ms), funding(last_time))
        markets = {name: market for name in ("A", "B", "C", "D")}
        quality = trend_basket_data_quality(
            markets,
            interval_ms=interval_ms,
            min_markets=10,
            min_span_days=1,
        )
        result = trend_basket_report(
            markets,
            3,
            3,
            5,
            interval_ms=interval_ms,
            min_markets=10,
            min_span_days=1,
            fold_days=1,
        )

        self.assertFalse(quality["interval_admitted"])
        self.assertFalse(quality["admitted"])
        self.assertEqual(result["verdict"], "DATA_LIMITED_NON_CONCLUSIVE")


if __name__ == "__main__":
    unittest.main()
