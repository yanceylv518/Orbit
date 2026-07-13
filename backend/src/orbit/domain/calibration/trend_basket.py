from __future__ import annotations

import math
import statistics
from bisect import bisect_right
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint, MarketCandle


MarketHistory = tuple[Sequence[MarketCandle], Sequence[FundingPoint]]


def _longest_contiguous_run(times: Sequence[int], interval_ms: int) -> list[int]:
    best: list[int] = []
    current: list[int] = []
    for value in times:
        if current and value - current[-1] != interval_ms:
            if len(current) > len(best):
                best = current
            current = []
        current.append(value)
    return current if len(current) > len(best) else best


def trend_basket_data_quality(
    markets: Mapping[str, MarketHistory],
    *,
    interval_ms: int,
    min_markets: int = 10,
    min_span_days: int = 1_095,
    min_funding_coverage: float = 0.99,
) -> dict[str, Any]:
    if interval_ms < 1 or min_markets < 2 or min_span_days < 1:
        raise ValueError("invalid trend basket data-quality settings")
    if not 0 < min_funding_coverage <= 1:
        raise ValueError("min_funding_coverage must be in (0, 1]")

    funding_interval_ms = 8 * 3_600_000
    market_reports: dict[str, dict[str, Any]] = {}
    individually_eligible = []
    for name, (raw_candles, raw_funding) in markets.items():
        candles = sorted(raw_candles, key=lambda item: item.close_time_ms)
        candle_times = sorted({item.close_time_ms for item in candles})
        run = _longest_contiguous_run(candle_times, interval_ms)
        if run:
            start_ms, end_ms = run[0], run[-1]
            span_days = (end_ms - start_ms) / 86_400_000
            expected_funding = max(1, math.floor((end_ms - start_ms) / funding_interval_ms))
            funding_times = {
                point.funding_time_ms
                for point in raw_funding
                if start_ms < point.funding_time_ms <= end_ms
            }
            funding_count = len(funding_times)
            funding_coverage = min(1.0, funding_count / expected_funding)
            contiguous_candle_ratio = len(run) / len(candle_times) if candle_times else 0.0
        else:
            start_ms = end_ms = None
            span_days = funding_coverage = contiguous_candle_ratio = 0.0
            funding_count = 0
        eligible = (
            span_days >= min_span_days
            and funding_coverage >= min_funding_coverage
            and contiguous_candle_ratio >= 0.99
        )
        if eligible:
            individually_eligible.append(name)
        market_reports[name] = {
            "candles": len(candle_times),
            "contiguous_candles": len(run),
            "contiguous_candle_ratio": contiguous_candle_ratio,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "span_days": span_days,
            "funding_points": funding_count,
            "funding_coverage": funding_coverage,
            "eligible": eligible,
        }

    common_run: list[int] = []
    if len(individually_eligible) >= 2:
        common_times = set.intersection(*(
            {
                candle.close_time_ms
                for candle in markets[name][0]
            }
            for name in individually_eligible
        ))
        common_run = _longest_contiguous_run(sorted(common_times), interval_ms)
    common_span_days = (
        (common_run[-1] - common_run[0]) / 86_400_000 if common_run else 0.0
    )
    interval_admitted = interval_ms >= 4 * 3_600_000
    admitted = (
        len(individually_eligible) >= min_markets
        and common_span_days >= min_span_days
        and interval_admitted
    )
    return {
        "provided_markets": len(markets),
        "eligible_markets": individually_eligible,
        "eligible_market_count": len(individually_eligible),
        "required_markets": min_markets,
        "interval_ms": interval_ms,
        "interval_admitted": interval_admitted,
        "required_span_days": min_span_days,
        "common_start_ms": common_run[0] if common_run else None,
        "common_end_ms": common_run[-1] if common_run else None,
        "common_span_days": common_span_days,
        "common_candles": len(common_run),
        "min_funding_coverage": min_funding_coverage,
        "markets": market_reports,
        "admitted": admitted,
    }


def trend_performance_summary(
    net_returns_pct: Sequence[float],
    *,
    periods_per_year: float,
    fold_periods: int,
) -> dict[str, Any]:
    if periods_per_year <= 0 or fold_periods < 1:
        raise ValueError("periods_per_year and fold_periods must be positive")
    returns = [float(value) / 100 for value in net_returns_pct]
    equity = 1.0
    peak = 1.0
    max_drawdown_pct = 0.0
    for value in returns:
        equity *= 1 + value
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown_pct = max(max_drawdown_pct, (peak - equity) / peak * 100)
    total_return_pct = (equity - 1) * 100
    years = len(returns) / periods_per_year if returns else 0.0
    annualized_return_pct = (
        (equity ** (1 / years) - 1) * 100
        if years > 0 and equity > 0
        else 0.0
    )
    period_std = statistics.stdev(returns) if len(returns) > 1 else 0.0
    annualized_volatility_pct = period_std * math.sqrt(periods_per_year) * 100
    sharpe = (
        statistics.mean(returns) / period_std * math.sqrt(periods_per_year)
        if period_std > 0
        else 0.0
    )
    folds = []
    for start in range(0, len(returns) - fold_periods + 1, fold_periods):
        fold_equity = 1.0
        for value in returns[start:start + fold_periods]:
            fold_equity *= 1 + value
        folds.append((fold_equity - 1) * 100)
    profitable_folds = sum(value > 0 for value in folds)
    performance_bar_pass = (
        annualized_return_pct > 0
        and sharpe >= 0.5
        and max_drawdown_pct <= 20
        and bool(folds)
        and profitable_folds > len(folds) / 2
    )
    return {
        "periods": len(returns),
        "years": years,
        "total_net_return_pct": total_return_pct,
        "annualized_net_return_pct": annualized_return_pct,
        "annualized_volatility_pct": annualized_volatility_pct,
        "sharpe": sharpe,
        "max_drawdown_pct": max_drawdown_pct,
        "fold_returns_pct": folds,
        "folds": len(folds),
        "profitable_folds": profitable_folds,
        "performance_bar_pass": performance_bar_pass,
    }


def trend_basket_report(
    markets: Mapping[str, MarketHistory],
    momentum_lookback: int,
    volatility_lookback: int,
    rebalance_ticks: int,
    *,
    interval_ms: int,
    target_portfolio_vol: float = 0.10,
    gross_cap: float = 1.0,
    roundtrip_cost_pct: float = 0.14,
    evaluation_start_ms: int | None = None,
    evaluation_end_ms: int | None = None,
    min_markets: int = 10,
    min_span_days: int = 1_095,
    min_funding_coverage: float = 0.99,
    fold_days: int = 365,
) -> dict[str, Any]:
    if len(markets) < 2:
        raise ValueError("at least two markets are required")
    if min(momentum_lookback, volatility_lookback, rebalance_ticks, interval_ms) < 1:
        raise ValueError("trend lookbacks, rebalance ticks, and interval must be positive")
    if target_portfolio_vol <= 0 or gross_cap <= 0 or roundtrip_cost_pct < 0:
        raise ValueError("trend risk and cost settings are invalid")

    quality = trend_basket_data_quality(
        markets,
        interval_ms=interval_ms,
        min_markets=min_markets,
        min_span_days=min_span_days,
        min_funding_coverage=min_funding_coverage,
    )
    usable_names = quality["eligible_markets"] or list(markets)
    common_times = set.intersection(*(
        {candle.close_time_ms for candle in markets[name][0]}
        for name in usable_names
    ))
    times = _longest_contiguous_run(sorted(common_times), interval_ms)
    warmup = max(momentum_lookback, volatility_lookback)
    if len(times) <= warmup + 2:
        raise ValueError("insufficient common candle history for trend lookbacks")

    if evaluation_end_ms is not None:
        times = [value for value in times if value <= evaluation_end_ms]
    if len(times) <= warmup + 2:
        raise ValueError("insufficient history before evaluation end")
    default_start_index = warmup + 1
    evaluation_start = evaluation_start_ms or times[default_start_index]
    evaluation_end = evaluation_end_ms or times[-1]
    if evaluation_start >= evaluation_end:
        raise ValueError("evaluation start must precede evaluation end")

    candles_by_market = {
        name: {candle.close_time_ms: candle for candle in markets[name][0]}
        for name in usable_names
    }
    closes = {
        name: [float(candles_by_market[name][time].close) for time in times]
        for name in usable_names
    }
    funding_data = {}
    for name in usable_names:
        funding_by_time = {
            point.funding_time_ms: float(point.funding_rate)
            for point in markets[name][1]
        }
        slot_times = sorted(funding_by_time)
        prefix = [0.0]
        for slot in slot_times:
            prefix.append(prefix[-1] + funding_by_time[slot])
        funding_data[name] = (slot_times, prefix)

    periods_per_year = 365 * 86_400_000 / interval_ms
    fold_periods = max(1, round(fold_days * 86_400_000 / interval_ms))
    weights = {name: 0.0 for name in usable_names}
    pending: dict[str, Any] | None = None
    net_returns_pct: list[float] = []
    rebalances: list[dict[str, Any]] = []
    total_turnover = 0.0
    total_cost_pct = 0.0
    price_contributions = {name: 0.0 for name in usable_names}
    funding_contributions = {name: 0.0 for name in usable_names}

    for index in range(1, len(times)):
        previous_time = times[index - 1]
        current_time = times[index]
        price_returns = {
            name: closes[name][index] / closes[name][index - 1] - 1
            for name in usable_names
        }
        funding_rates = {}
        for name in usable_names:
            slot_times, prefix = funding_data[name]
            start = bisect_right(slot_times, previous_time)
            end = bisect_right(slot_times, current_time)
            funding_rates[name] = prefix[end] - prefix[start]

        price_return = sum(weights[name] * price_returns[name] for name in usable_names)
        funding_return = -sum(weights[name] * funding_rates[name] for name in usable_names)
        period_return = price_return + funding_return
        for name in usable_names:
            price_contributions[name] += weights[name] * price_returns[name] * 100
            funding_contributions[name] += -weights[name] * funding_rates[name] * 100

        denominator = 1 + period_return
        if denominator > 0:
            weights = {
                name: weights[name] * (1 + price_returns[name]) / denominator
                for name in usable_names
            }

        turnover = 0.0
        cost_return = 0.0
        if pending is not None and pending["execution_index"] == index:
            target_weights = pending["target_weights"]
            turnover = 0.5 * sum(
                abs(target_weights[name] - weights[name]) for name in usable_names
            )
            cost_return = turnover * roundtrip_cost_pct / 100
            total_turnover += turnover
            total_cost_pct += cost_return * 100
            period_return -= cost_return
            weights = dict(target_weights)
            rebalances.append({
                "signal_time_ms": pending["signal_time_ms"],
                "execution_time_ms": current_time,
                "signals": pending["signals"],
                "annualized_volatility": pending["annualized_volatility"],
                "target_weights": target_weights,
                "gross_exposure": sum(abs(value) for value in target_weights.values()),
                "turnover": turnover,
                "cost_pct": cost_return * 100,
            })
            pending = None

        if evaluation_start <= current_time <= evaluation_end:
            net_returns_pct.append(period_return * 100)

        can_schedule = (
            index >= warmup
            and (index - warmup) % rebalance_ticks == 0
            and index + 2 < len(times)
            and evaluation_start <= times[index + 1] <= evaluation_end
        )
        if can_schedule:
            signals = {}
            annualized_volatility = {}
            for name in usable_names:
                momentum = closes[name][index] / closes[name][index - momentum_lookback] - 1
                signals[name] = 1 if momentum > 0 else -1 if momentum < 0 else 0
                log_returns = [
                    math.log(closes[name][offset] / closes[name][offset - 1])
                    for offset in range(index - volatility_lookback + 1, index + 1)
                ]
                annualized_volatility[name] = (
                    statistics.stdev(log_returns) * math.sqrt(periods_per_year)
                    if len(log_returns) > 1
                    else 0.0
                )
            active = [
                name for name in usable_names
                if signals[name] and annualized_volatility[name] > 0
            ]
            target_weights = {name: 0.0 for name in usable_names}
            if active:
                for name in active:
                    target_weights[name] = (
                        signals[name]
                        * target_portfolio_vol
                        / (math.sqrt(len(active)) * annualized_volatility[name])
                    )
                gross = sum(abs(value) for value in target_weights.values())
                if gross > gross_cap:
                    scale = gross_cap / gross
                    target_weights = {
                        name: value * scale for name, value in target_weights.items()
                    }
            pending = {
                "signal_time_ms": current_time,
                "execution_index": index + 1,
                "signals": signals,
                "annualized_volatility": annualized_volatility,
                "target_weights": target_weights,
            }

    if net_returns_pct:
        liquidation_turnover = 0.5 * sum(abs(value) for value in weights.values())
        liquidation_cost_pct = liquidation_turnover * roundtrip_cost_pct
        net_returns_pct[-1] -= liquidation_cost_pct
        total_turnover += liquidation_turnover
        total_cost_pct += liquidation_cost_pct
    else:
        liquidation_turnover = 0.0
        liquidation_cost_pct = 0.0

    performance = trend_performance_summary(
        net_returns_pct,
        periods_per_year=periods_per_year,
        fold_periods=fold_periods,
    )
    admitted = quality["admitted"] and performance["performance_bar_pass"]
    return {
        "momentum_lookback": momentum_lookback,
        "volatility_lookback": volatility_lookback,
        "rebalance_ticks": rebalance_ticks,
        "target_portfolio_vol": target_portfolio_vol,
        "gross_cap": gross_cap,
        "roundtrip_cost_pct": roundtrip_cost_pct,
        "evaluation_start_ms": evaluation_start,
        "evaluation_end_ms": evaluation_end,
        "data_quality": quality,
        "market_count": len(usable_names),
        "markets": usable_names,
        "rebalances": rebalances,
        "rebalance_count": len(rebalances),
        "total_turnover": total_turnover,
        "total_transaction_cost_pct": total_cost_pct,
        "liquidation_turnover": liquidation_turnover,
        "liquidation_cost_pct": liquidation_cost_pct,
        "price_contribution_pct": price_contributions,
        "funding_contribution_pct": funding_contributions,
        "net_returns_pct": net_returns_pct,
        **performance,
        "admitted": admitted,
        "verdict": (
            "PASS" if admitted
            else "FAIL" if quality["admitted"]
            else "DATA_LIMITED_NON_CONCLUSIVE"
        ),
    }
