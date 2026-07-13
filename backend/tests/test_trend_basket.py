import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import FundingPoint, MarketCandle
from orbit.domain.calibration.trend_basket import (
    trend_basket_data_quality,
    trend_basket_report,
    trend_basket_tb3_walk_forward,
    trend_basket_walk_forward,
    trend_performance_summary,
    trend_tb3_admission,
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

    def test_drawdown_throttle_scales_only_future_targets(self):
        prices = [100, 101, 102, 103, 104, 90, 89, 88, 87, 86, 85, 84]
        last_time = (len(prices) - 1) * DAY_MS
        markets = {
            name: (candles(prices), funding(last_time))
            for name in ("A", "B")
        }

        result = report(
            markets,
            rebalance_ticks=1,
            drawdown_threshold_pct=1,
            drawdown_risk_scale=0.5,
        )

        self.assertEqual(result["rebalances"][0]["risk_scale"], 1.0)
        throttled = [
            item for item in result["rebalances"]
            if item["risk_scale"] == 0.5
        ]
        self.assertTrue(throttled)
        self.assertTrue(all(
            item["drawdown_at_signal_pct"] >= 1 for item in throttled
        ))
        self.assertEqual(result["throttle_trigger_count"], len(throttled))

    def test_evaluation_window_resets_drawdown_state(self):
        prices = [100, 101, 102, 103, 104, 90, 89, 88, 90, 92, 94, 96]
        last_time = (len(prices) - 1) * DAY_MS
        markets = {
            name: (candles(prices), funding(last_time))
            for name in ("A", "B")
        }

        result = report(
            markets,
            rebalance_ticks=1,
            evaluation_start_ms=8 * DAY_MS,
            drawdown_threshold_pct=1,
            drawdown_risk_scale=0.5,
        )

        first = result["rebalances"][0]
        self.assertEqual(first["risk_scale"], 1.0)
        self.assertEqual(first["drawdown_at_signal_pct"], 0.0)

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

    def test_tb3_metrics_include_downside_rolling_and_drawdown_duration(self):
        summary = trend_performance_summary(
            [10.0, -5.0, 2.0, 3.0],
            periods_per_year=12,
            fold_periods=2,
            rolling_window_periods=2,
            rolling_step_periods=1,
        )

        self.assertIsNotNone(summary["calmar"])
        self.assertIsNotNone(summary["sortino"])
        self.assertAlmostEqual(summary["max_drawdown_pct"], 5.0)
        self.assertEqual(summary["max_drawdown_duration_periods"], 3)
        self.assertEqual(summary["max_drawdown_duration_months"], 3.0)
        self.assertEqual(summary["rolling_windows"], 3)
        self.assertAlmostEqual(summary["worst_rolling_return_pct"], -3.1)
        self.assertEqual(summary["positive_rolling_windows"], 2)
        self.assertAlmostEqual(summary["positive_rolling_window_ratio"], 2 / 3)

    def test_tb3_admission_reports_each_frozen_condition(self):
        performance = {
            "total_net_return_pct": 12.0,
            "max_drawdown_pct": 20.0,
            "calmar": 0.6,
            "calmar_infinite": False,
            "sortino": 0.8,
            "sortino_infinite": False,
            "worst_rolling_return_pct": -10.0,
            "positive_rolling_window_ratio": 0.6,
            "max_drawdown_duration_months": 12.0,
        }

        admitted = trend_tb3_admission(performance)
        performance["positive_rolling_window_ratio"] = 0.54
        rejected = trend_tb3_admission(performance)

        self.assertTrue(admitted["admitted"])
        self.assertTrue(all(admitted["conditions"].values()))
        self.assertFalse(rejected["admitted"])
        self.assertFalse(rejected["conditions"]["positive_rolling_12m_ratio"])

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

    def test_walk_forward_selection_does_not_read_future_prices(self):
        original = trending_markets(length=70)
        changed = {}
        cutoff = 40 * DAY_MS
        for name, (market_candles, points) in original.items():
            future_changed = [
                MarketCandle(
                    item.close_time_ms,
                    item.close * 3,
                    item.close * 3,
                    item.close * 3,
                    item.close * 3,
                )
                if item.close_time_ms >= cutoff else item
                for item in market_candles
            ]
            changed[name] = (future_changed, points)
        candidates = [
            {"id": "vol06_none", "target_portfolio_vol": 0.06},
            {"id": "vol08_none", "target_portfolio_vol": 0.08},
        ]
        windows = [{
            "id": "WF1",
            "training_end_ms": 29 * DAY_MS,
            "oos_start_ms": 30 * DAY_MS,
            "oos_end_ms": 39 * DAY_MS,
        }]
        kwargs = {
            "interval_ms": DAY_MS,
            "momentum_lookback": 3,
            "volatility_lookback": 3,
            "rebalance_ticks": 5,
            "min_markets": 2,
            "min_span_days": 1,
            "fold_days": 5,
        }

        before = trend_basket_walk_forward(original, candidates, windows, **kwargs)
        after = trend_basket_walk_forward(changed, candidates, windows, **kwargs)

        self.assertEqual(
            before["steps"][0]["selected_candidate"],
            after["steps"][0]["selected_candidate"],
        )
        self.assertTrue(all(
            item["report"]["evaluation_end_ms"] <= 29 * DAY_MS
            for item in before["steps"][0]["training_candidates"]
        ))

    def test_walk_forward_rejects_overlapping_oos_windows(self):
        candidates = [{"id": "vol06_none", "target_portfolio_vol": 0.06}]
        windows = [
            {
                "id": "WF1",
                "training_end_ms": 10,
                "oos_start_ms": 20,
                "oos_end_ms": 40,
            },
            {
                "id": "WF2",
                "training_end_ms": 30,
                "oos_start_ms": 40,
                "oos_end_ms": 50,
            },
        ]

        with self.assertRaisesRegex(ValueError, "must not overlap"):
            trend_basket_walk_forward(
                trending_markets(),
                candidates,
                windows,
                interval_ms=DAY_MS,
                momentum_lookback=3,
                volatility_lookback=3,
                rebalance_ticks=5,
                min_markets=2,
                min_span_days=1,
            )

    def test_tb3_selects_highest_eligible_vol_without_future_prices(self):
        original = trending_markets(length=70)
        changed = {}
        for name, (market_candles, points) in original.items():
            future_changed = [
                MarketCandle(
                    item.close_time_ms,
                    item.close * 4,
                    item.close * 4,
                    item.close * 4,
                    item.close * 4,
                )
                if item.close_time_ms >= 40 * DAY_MS else item
                for item in market_candles
            ]
            changed[name] = (future_changed, points)
        candidates = [
            {"id": "vol10", "target_portfolio_vol": 0.10},
            {"id": "vol20", "target_portfolio_vol": 0.20},
        ]
        windows = [{
            "id": "WF1",
            "training_end_ms": 29 * DAY_MS,
            "oos_start_ms": 30 * DAY_MS,
            "oos_end_ms": 39 * DAY_MS,
        }]
        kwargs = {
            "interval_ms": DAY_MS,
            "momentum_lookback": 3,
            "volatility_lookback": 3,
            "rebalance_ticks": 5,
            "min_markets": 2,
            "min_span_days": 1,
        }

        before = trend_basket_tb3_walk_forward(
            original, candidates, windows, **kwargs,
        )
        after = trend_basket_tb3_walk_forward(
            changed, candidates, windows, **kwargs,
        )

        self.assertEqual(before["steps"][0]["selected_candidate"]["id"], "vol20")
        self.assertEqual(
            before["steps"][0]["selected_candidate"],
            after["steps"][0]["selected_candidate"],
        )
        self.assertTrue(all(
            item["report"]["evaluation_end_ms"] <= 29 * DAY_MS
            for item in before["steps"][0]["training_candidates"]
        ))

    def test_tb3_rejects_overlapping_oos_windows(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            trend_basket_tb3_walk_forward(
                trending_markets(),
                [{"id": "vol10", "target_portfolio_vol": 0.10}],
                [
                    {
                        "id": "WF1",
                        "training_end_ms": 10,
                        "oos_start_ms": 20,
                        "oos_end_ms": 40,
                    },
                    {
                        "id": "WF2",
                        "training_end_ms": 30,
                        "oos_start_ms": 40,
                        "oos_end_ms": 50,
                    },
                ],
                interval_ms=DAY_MS,
                momentum_lookback=3,
                volatility_lookback=3,
                rebalance_ticks=5,
                min_markets=2,
                min_span_days=1,
            )


if __name__ == "__main__":
    unittest.main()
