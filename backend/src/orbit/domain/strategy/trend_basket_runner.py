from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint, MarketCandle


TB4_SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
)
TB4_INTERVAL_MS = 4 * 3_600_000
TB4_MOMENTUM_LOOKBACKS = (14 * 6, 28 * 6, 56 * 6, 84 * 6, 168 * 6)
TB4_VOLATILITY_LOOKBACK = 28 * 6
TB4_REBALANCE_TICKS = 7 * 6
TB4_TARGET_PORTFOLIO_VOL = 0.10
TB4_GROSS_CAP = 1.0
TB4_ROUNDTRIP_COST_PCT = 0.14


@dataclass(frozen=True)
class TrendBasketSpec:
    symbols: tuple[str, ...]
    interval_ms: int
    momentum_lookbacks: tuple[int, ...]
    volatility_lookback: int
    rebalance_ticks: int
    target_portfolio_vol: float
    gross_cap: float
    roundtrip_cost_pct: float

    @property
    def warmup_ticks(self) -> int:
        return max(max(self.momentum_lookbacks), self.volatility_lookback)


TB4_SPEC = TrendBasketSpec(
    symbols=TB4_SYMBOLS,
    interval_ms=TB4_INTERVAL_MS,
    momentum_lookbacks=TB4_MOMENTUM_LOOKBACKS,
    volatility_lookback=TB4_VOLATILITY_LOOKBACK,
    rebalance_ticks=TB4_REBALANCE_TICKS,
    target_portfolio_vol=TB4_TARGET_PORTFOLIO_VOL,
    gross_cap=TB4_GROSS_CAP,
    roundtrip_cost_pct=TB4_ROUNDTRIP_COST_PCT,
)


class FrozenTrendBasketRunner:
    """Incremental paper runner for the parameter-frozen TB4 trend basket."""

    def __init__(self, *, _spec: TrendBasketSpec = TB4_SPEC):
        self.spec = _spec
        self.times: list[int] = []
        self.closes = {symbol: [] for symbol in self.spec.symbols}
        self.weights = {symbol: 0.0 for symbol in self.spec.symbols}
        self.pending: dict[str, Any] | None = None
        self.net_returns_pct: list[float] = []
        self.rebalances: list[dict[str, Any]] = []
        self.equity = 1.0
        self.peak = 1.0
        self.current_drawdown_pct = 0.0
        self.total_turnover = 0.0
        self.total_cost_pct = 0.0

    def on_close(
        self,
        close_time_ms: int,
        closes: Mapping[str, float],
        funding_rates: Mapping[str, float] | None = None,
        *,
        record_return: bool = True,
        allow_signal: bool = True,
    ) -> dict[str, Any]:
        self._validate_close(close_time_ms, closes)
        funding = funding_rates or {}
        current_closes = {symbol: float(closes[symbol]) for symbol in self.spec.symbols}
        self.times.append(int(close_time_ms))
        for symbol, value in current_closes.items():
            self.closes[symbol].append(value)
        index = len(self.times) - 1
        if index == 0:
            return self._result(close_time_ms, None, None)

        price_returns = {
            symbol: self.closes[symbol][index] / self.closes[symbol][index - 1] - 1
            for symbol in self.spec.symbols
        }
        price_return = sum(
            self.weights[symbol] * price_returns[symbol]
            for symbol in self.spec.symbols
        )
        funding_return = -sum(
            self.weights[symbol] * float(funding.get(symbol, 0.0))
            for symbol in self.spec.symbols
        )
        period_return = price_return + funding_return

        denominator = 1 + period_return
        if denominator > 0:
            self.weights = {
                symbol: self.weights[symbol] * (1 + price_returns[symbol]) / denominator
                for symbol in self.spec.symbols
            }

        executed = None
        if self.pending is not None and self.pending["execution_index"] == index:
            target = self.pending["target_weights"]
            turnover = 0.5 * sum(
                abs(target[symbol] - self.weights[symbol])
                for symbol in self.spec.symbols
            )
            cost_return = turnover * self.spec.roundtrip_cost_pct / 100
            period_return -= cost_return
            self.total_turnover += turnover
            self.total_cost_pct += cost_return * 100
            self.weights = dict(target)
            executed = {
                "signal_time_ms": self.pending["signal_time_ms"],
                "execution_time_ms": int(close_time_ms),
                "signals": dict(self.pending["signals"]),
                "annualized_volatility": dict(self.pending["annualized_volatility"]),
                "target_weights": dict(target),
                "gross_exposure": sum(abs(value) for value in target.values()),
                "turnover": turnover,
                "cost_pct": cost_return * 100,
                "drawdown_at_signal_pct": self.pending["drawdown_at_signal_pct"],
                "risk_scale": 1.0,
            }
            self.rebalances.append(executed)
            self.pending = None

        if record_return:
            self.net_returns_pct.append(period_return * 100)
            self.equity *= 1 + period_return
            self.peak = max(self.peak, self.equity)
            self.current_drawdown_pct = (
                (self.peak - self.equity) / self.peak * 100 if self.peak > 0 else 100.0
            )

        scheduled = None
        if allow_signal and index >= self.spec.warmup_ticks and (
            index - self.spec.warmup_ticks
        ) % self.spec.rebalance_ticks == 0:
            scheduled = self._schedule(index, close_time_ms)

        return self._result(close_time_ms, executed, scheduled, period_return)

    def finalize_replay(self) -> None:
        """Apply the offline estimator's terminal liquidation cost for alignment only."""
        if not self.net_returns_pct:
            return
        turnover = 0.5 * sum(abs(value) for value in self.weights.values())
        cost_pct = turnover * self.spec.roundtrip_cost_pct
        self.net_returns_pct[-1] -= cost_pct
        self.total_turnover += turnover
        self.total_cost_pct += cost_pct

    def snapshot(self) -> dict[str, Any]:
        return {
            "protocol": "TB4_FROZEN_TREND_BASKET",
            "status": "warming_up" if len(self.times) <= self.spec.warmup_ticks else "running",
            "last_close_time_ms": self.times[-1] if self.times else None,
            "tick_count": len(self.times),
            "warmup_ticks": self.spec.warmup_ticks,
            "weights": dict(self.weights),
            "pending": dict(self.pending) if self.pending else None,
            "equity": self.equity,
            "current_drawdown_pct": self.current_drawdown_pct,
            "rebalance_count": len(self.rebalances),
            "total_turnover": self.total_turnover,
            "total_transaction_cost_pct": self.total_cost_pct,
        }

    def _schedule(self, index: int, close_time_ms: int) -> dict[str, Any]:
        periods_per_year = 365 * 86_400_000 / self.spec.interval_ms
        signals = {}
        annualized_volatility = {}
        for symbol in self.spec.symbols:
            prices = self.closes[symbol]
            components = []
            for lookback in self.spec.momentum_lookbacks:
                momentum = prices[index] / prices[index - lookback] - 1
                components.append(1 if momentum > 0 else -1 if momentum < 0 else 0)
            signals[symbol] = sum(components) / len(components)
            log_returns = [
                math.log(prices[offset] / prices[offset - 1])
                for offset in range(index - self.spec.volatility_lookback + 1, index + 1)
            ]
            annualized_volatility[symbol] = (
                statistics.stdev(log_returns) * math.sqrt(periods_per_year)
                if len(log_returns) > 1 else 0.0
            )
        active = [
            symbol for symbol in self.spec.symbols
            if signals[symbol] and annualized_volatility[symbol] > 0
        ]
        target = {symbol: 0.0 for symbol in self.spec.symbols}
        for symbol in active:
            target[symbol] = (
                signals[symbol] * self.spec.target_portfolio_vol
                / (math.sqrt(len(active)) * annualized_volatility[symbol])
            )
        gross = sum(abs(value) for value in target.values())
        if gross > self.spec.gross_cap:
            scale = self.spec.gross_cap / gross
            target = {symbol: value * scale for symbol, value in target.items()}
        self.pending = {
            "signal_time_ms": int(close_time_ms),
            "execution_index": index + 1,
            "signals": signals,
            "annualized_volatility": annualized_volatility,
            "target_weights": target,
            "drawdown_at_signal_pct": self.current_drawdown_pct,
            "risk_scale": 1.0,
        }
        return dict(self.pending)

    def _validate_close(self, close_time_ms: int, closes: Mapping[str, float]) -> None:
        if set(closes) != set(self.spec.symbols):
            raise ValueError("TB4 close must contain the exact frozen 12-market universe")
        if self.times and close_time_ms - self.times[-1] != self.spec.interval_ms:
            raise ValueError("TB4 closes must form a contiguous 4h timeline")
        if any(float(value) <= 0 for value in closes.values()):
            raise ValueError("TB4 close prices must be positive")

    def _result(
        self,
        close_time_ms: int,
        executed: dict[str, Any] | None,
        scheduled: dict[str, Any] | None,
        period_return: float | None = None,
    ) -> dict[str, Any]:
        return {
            "close_time_ms": int(close_time_ms),
            "net_return_pct": period_return * 100 if period_return is not None else None,
            "executed_rebalance": executed,
            "scheduled_rebalance": scheduled,
            "snapshot": self.snapshot(),
        }


def replay_frozen_trend_basket(
    markets: Mapping[
        str,
        tuple[Sequence[MarketCandle], Sequence[FundingPoint]],
    ],
    *,
    evaluation_start_ms: int | None = None,
    evaluation_end_ms: int | None = None,
) -> FrozenTrendBasketRunner:
    """Replay frozen history with the same boundary semantics as the offline estimator."""
    if set(markets) != set(TB4_SPEC.symbols):
        raise ValueError("TB4 replay requires the exact frozen 12-market universe")
    common_times = sorted(set.intersection(*(
        {candle.close_time_ms for candle in markets[symbol][0]}
        for symbol in TB4_SPEC.symbols
    )))
    contiguous: list[int] = []
    current: list[int] = []
    for value in common_times:
        if current and value - current[-1] != TB4_SPEC.interval_ms:
            if len(current) > len(contiguous):
                contiguous = current
            current = []
        current.append(value)
    if len(current) > len(contiguous):
        contiguous = current
    times = contiguous
    if evaluation_end_ms is not None:
        times = [value for value in times if value <= evaluation_end_ms]
    if len(times) <= TB4_SPEC.warmup_ticks + 2:
        raise ValueError("insufficient common history for TB4 replay")
    evaluation_start = evaluation_start_ms or times[TB4_SPEC.warmup_ticks + 1]
    evaluation_end = evaluation_end_ms or times[-1]

    candles_by_symbol = {
        symbol: {candle.close_time_ms: candle for candle in markets[symbol][0]}
        for symbol in TB4_SPEC.symbols
    }
    funding_prefix = {}
    for symbol in TB4_SPEC.symbols:
        by_time = {
            point.funding_time_ms: float(point.funding_rate)
            for point in markets[symbol][1]
        }
        event_times = sorted(by_time)
        prefix = [0.0]
        for event_time in event_times:
            prefix.append(prefix[-1] + by_time[event_time])
        funding_prefix[symbol] = (event_times, prefix)

    runner = FrozenTrendBasketRunner()
    for index, current_time in enumerate(times):
        previous_time = times[index - 1] if index else current_time - TB4_SPEC.interval_ms
        closes = {
            symbol: candles_by_symbol[symbol][current_time].close
            for symbol in TB4_SPEC.symbols
        }
        funding_rates = {}
        for symbol in TB4_SPEC.symbols:
            event_times, prefix = funding_prefix[symbol]
            start = bisect_right(event_times, previous_time)
            end = bisect_right(event_times, current_time)
            funding_rates[symbol] = prefix[end] - prefix[start]
        runner.on_close(
            current_time,
            closes,
            funding_rates,
            record_return=evaluation_start <= current_time <= evaluation_end,
            allow_signal=(
                index + 2 < len(times)
                and evaluation_start <= times[index + 1] <= evaluation_end
            ),
        )
    runner.finalize_replay()
    return runner
