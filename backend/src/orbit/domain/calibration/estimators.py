from __future__ import annotations

import math
import random
import statistics
from bisect import bisect_right
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint, MarketCandle
from orbit.domain.strategy.regime import DEFAULT_REGIME_CONFIG, RANGE, RegimeGate

"""π̂ 估计与几何扫描（STRATEGY_LOGIC §2 / §10.1 的离线标定内核）。

策略的品种准入条件：π > 1 − (a − c) / θ
其中 π = "偏离锚点 a% 的行情在触及 θ% 前回归"的概率，
a = 偏斜触发幅度，θ = 趋势确认幅度，c = 一来一回成本率。

本模块只做纯计算：锚点重演统计、Wilson 置信区间、期望值与扫描。
数据获取与 CLI 在 backend/tools/ 下。
"""


def excursion_outcomes(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    reversion_pct: float = 0.25,
) -> tuple[int, int]:
    """锚点重演：返回 (回归次数, 延伸次数)。

    规则（与策略语义一致的一阶简化）：
    - 锚点 = 当前段起点；|m| 首次 ≥ a 记一次 excursion（方向锁定）；
    - 之后同方向 |m| ≥ θ → 延伸（趋势确认，偏斜押注止损）；
    - |m| 回落到 ≤ reversion_pct（近似回到锚点）→ 回归（偏斜押注获利）；
    - 每次结束在当前价重锚，继续统计。
    """
    if a_pct <= 0 or theta_pct <= a_pct:
        raise ValueError("需要 0 < a < θ")
    reversions = 0
    extensions = 0
    anchor: float | None = None
    direction = 0  # 0=无 excursion，+1 向上，-1 向下

    for price in closes:
        if price <= 0:
            continue
        if anchor is None:
            anchor = price
            continue
        move_pct = (price / anchor - 1) * 100
        if direction == 0:
            if abs(move_pct) >= a_pct:
                direction = 1 if move_pct > 0 else -1
            continue
        directed = move_pct * direction
        if directed >= theta_pct:
            extensions += 1
            anchor = price
            direction = 0
        elif directed <= reversion_pct:
            reversions += 1
            anchor = price
            direction = 0
    return reversions, extensions


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    denom = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def pi_required(a_pct: float, theta_pct: float, cost_pct: float) -> float:
    """盈亏平衡回归概率：π > 1 − (a − c)/θ。"""
    return 1 - (a_pct - cost_pct) / theta_pct


def expected_value_per_bet(pi: float, a_pct: float, theta_pct: float, cost_pct: float) -> float:
    """单次偏斜押注期望（单位：占名义的 %）：E = π·a − (1−π)(θ−a) − c。"""
    return pi * a_pct - (1 - pi) * (theta_pct - a_pct) - cost_pct


def horizon_reversion_report(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    cost_pct: float,
    max_holding_ticks: int,
    *,
    reversion_pct: float = 0.25,
) -> dict[str, Any]:
    """Mark counter-trend excursions to market at a fixed holding horizon."""
    if a_pct <= 0 or theta_pct <= a_pct:
        raise ValueError("需要 0 < a < θ")
    if max_holding_ticks < 1:
        raise ValueError("max_holding_ticks must be positive")

    anchor: float | None = None
    active: tuple[int, float, int] | None = None
    records: list[dict[str, Any]] = []
    for index, raw_price in enumerate(closes):
        price = float(raw_price)
        if price <= 0:
            continue
        if anchor is None:
            anchor = price
            continue

        move_pct = (price / anchor - 1) * 100
        if active is None:
            if abs(move_pct) >= a_pct:
                direction = 1 if move_pct > 0 else -1
                active = (direction, price, index)
            continue

        direction, entry_price, entry_index = active
        directed_from_anchor = move_pct * direction
        holding_ticks = index - entry_index
        outcome = None
        if directed_from_anchor >= theta_pct:
            outcome = "extension"
        elif directed_from_anchor <= reversion_pct:
            outcome = "reversion"
        elif holding_ticks >= max_holding_ticks:
            outcome = "timeout"
        if outcome is None:
            continue

        gross_return_pct = -direction * (price / entry_price - 1) * 100
        records.append({
            "outcome": outcome,
            "holding_ticks": holding_ticks,
            "gross_return_pct": gross_return_pct,
            "net_return_pct": gross_return_pct - cost_pct,
        })
        anchor = price
        active = None

    net_returns = [float(record["net_return_pct"]) for record in records]
    gross_returns = [float(record["gross_return_pct"]) for record in records]
    profitable = sum(value > 0 for value in net_returns)
    low, high = wilson_interval(profitable, len(records))
    return {
        "a_pct": a_pct,
        "theta_pct": theta_pct,
        "cost_pct": cost_pct,
        "max_holding_ticks": max_holding_ticks,
        "trades": len(records),
        "reversions": sum(record["outcome"] == "reversion" for record in records),
        "extensions": sum(record["outcome"] == "extension" for record in records),
        "timeouts": sum(record["outcome"] == "timeout" for record in records),
        "open_excursions": int(active is not None),
        "profitable_trades": profitable,
        "win_rate": profitable / len(records) if records else 0.0,
        "win_rate_ci_low": low,
        "win_rate_ci_high": high,
        "average_holding_ticks": (
            sum(int(record["holding_ticks"]) for record in records) / len(records)
            if records else 0.0
        ),
        "gross_return_pct": sum(gross_returns),
        "cost_drag_pct": len(records) * cost_pct,
        "net_return_pct": sum(net_returns),
        "expected_value_pct": sum(net_returns) / len(records) if records else 0.0,
        "max_drawdown_pct": max_drawdown(net_returns),
    }


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    samples: int = 10_000,
    seed: int = 20_260_713,
) -> tuple[float, float]:
    if samples < 1:
        raise ValueError("bootstrap samples must be positive")
    clean = [float(value) for value in values]
    if not clean:
        return 0.0, 0.0
    rng = random.Random(seed)
    size = len(clean)
    means = sorted(sum(rng.choices(clean, k=size)) / size for _ in range(samples))
    return percentile(means, 0.025), percentile(means, 0.975)


def percentile(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    position = (len(sorted_values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower]) * (1 - weight) + float(sorted_values[upper]) * weight


def funding_carry_return_summary(
    net_returns_pct: Sequence[float],
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_713,
) -> dict[str, Any]:
    returns = [float(value) for value in net_returns_pct]
    profitable = sum(value > 0 for value in returns)
    win_low, win_high = wilson_interval(profitable, len(returns))
    mean_low, mean_high = bootstrap_mean_interval(
        returns,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    mean = sum(returns) / len(returns) if returns else 0.0
    return {
        "events": len(returns),
        "profitable_events": profitable,
        "win_rate": profitable / len(returns) if returns else 0.0,
        "win_rate_ci_low": win_low,
        "win_rate_ci_high": win_high,
        "mean_net_carry_pct": mean,
        "median_net_carry_pct": statistics.median(returns) if returns else 0.0,
        "total_net_carry_pct": sum(returns),
        "worst_window_pct": min(returns) if returns else 0.0,
        "bootstrap_mean_ci_low": mean_low,
        "bootstrap_mean_ci_high": mean_high,
        "max_drawdown_pct": max_drawdown(returns),
        "admitted": len(returns) >= 30 and mean > 0 and mean_low > 0,
    }


def funding_carry_screen(
    funding_points: Sequence[FundingPoint],
    window_settlements: int,
    *,
    entry_exit_cost_pct: float = 0.38,
    rebalance_cost_pct_per_day: float = 0.02,
    settlements_per_day: int = 3,
    max_gap_ms: int = 12 * 3_600_000,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_713,
) -> dict[str, Any]:
    """Optimistic funding-only upper bound for a perfectly hedged carry."""
    if window_settlements < 1 or settlements_per_day < 1:
        raise ValueError("window_settlements and settlements_per_day must be positive")
    if entry_exit_cost_pct < 0 or rebalance_cost_pct_per_day < 0:
        raise ValueError("carry costs must not be negative")

    ordered = sorted(funding_points, key=lambda point: point.funding_time_ms)
    runs: list[list[FundingPoint]] = []
    for point in ordered:
        if not runs or point.funding_time_ms - runs[-1][-1].funding_time_ms > max_gap_ms:
            runs.append([point])
        else:
            runs[-1].append(point)

    holding_days = window_settlements / settlements_per_day
    total_cost_pct = entry_exit_cost_pct + rebalance_cost_pct_per_day * holding_days
    gross_returns = []
    for run in runs:
        for start in range(0, len(run) - window_settlements + 1, window_settlements):
            window = run[start:start + window_settlements]
            gross_returns.append(sum(abs(point.funding_rate) for point in window) * 100)
    net_returns = [gross - total_cost_pct for gross in gross_returns]
    summary = funding_carry_return_summary(
        net_returns,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    return {
        "window_settlements": window_settlements,
        "holding_days": holding_days,
        "entry_exit_cost_pct": entry_exit_cost_pct,
        "rebalance_cost_pct_per_day": rebalance_cost_pct_per_day,
        "total_cost_pct": total_cost_pct,
        "contiguous_runs": len(runs),
        "discarded_points": sum(len(run) % window_settlements for run in runs),
        "mean_gross_funding_pct": (
            sum(gross_returns) / len(gross_returns) if gross_returns else 0.0
        ),
        "median_gross_funding_pct": statistics.median(gross_returns) if gross_returns else 0.0,
        "net_returns_pct": net_returns,
        **summary,
    }


def extreme_funding_return_summary(
    net_returns_pct: Sequence[float],
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_713,
) -> dict[str, Any]:
    """Summarize cost-adjusted returns for an extreme-funding reaction sample."""
    returns = [float(value) for value in net_returns_pct]
    profitable = sum(value > 0 for value in returns)
    win_low, win_high = wilson_interval(profitable, len(returns))
    mean_low, mean_high = bootstrap_mean_interval(
        returns,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    mean = sum(returns) / len(returns) if returns else 0.0
    return {
        "events": len(returns),
        "profitable_events": profitable,
        "win_rate": profitable / len(returns) if returns else 0.0,
        "win_rate_ci_low": win_low,
        "win_rate_ci_high": win_high,
        "mean_net_return_pct": mean,
        "median_net_return_pct": statistics.median(returns) if returns else 0.0,
        "total_net_return_pct": sum(returns),
        "worst_event_pct": min(returns) if returns else 0.0,
        "bootstrap_mean_ci_low": mean_low,
        "bootstrap_mean_ci_high": mean_high,
        "max_drawdown_pct": max_drawdown(returns),
        "admitted": len(returns) >= 30 and mean > 0 and mean_low > 0,
    }


def extreme_funding_reaction_report(
    funding_points: Sequence[FundingPoint],
    candles: Sequence[MarketCandle],
    lookback_settlements: int,
    extreme_quantile: float,
    holding_ticks: int,
    *,
    cost_pct: float = 0.14,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_713,
) -> dict[str, Any]:
    """Audit a contrarian trade after historically extreme funding settlements.

    The rolling threshold excludes the current settlement. Entry is the first
    closed candle strictly after the funding timestamp, and accepted events do
    not overlap.
    """
    if lookback_settlements < 1 or holding_ticks < 1:
        raise ValueError("lookback_settlements and holding_ticks must be positive")
    if not 0 < extreme_quantile < 1:
        raise ValueError("extreme_quantile must be between zero and one")
    if cost_pct < 0:
        raise ValueError("cost_pct must not be negative")

    ordered_funding = sorted(funding_points, key=lambda point: point.funding_time_ms)
    ordered_candles = sorted(candles, key=lambda candle: candle.close_time_ms)
    candle_times = [candle.close_time_ms for candle in ordered_candles]
    records: list[dict[str, Any]] = []
    last_exit_time_ms = -1
    discarded_tail_events = 0

    for index in range(lookback_settlements, len(ordered_funding)):
        point = ordered_funding[index]
        history = ordered_funding[index - lookback_settlements:index]
        threshold = percentile(
            sorted(abs(item.funding_rate) for item in history),
            extreme_quantile,
        )
        if point.funding_rate == 0 or abs(point.funding_rate) < threshold:
            continue

        entry_index = bisect_right(candle_times, point.funding_time_ms)
        if entry_index >= len(ordered_candles):
            discarded_tail_events += 1
            continue
        entry = ordered_candles[entry_index]
        if entry.close_time_ms <= last_exit_time_ms:
            continue
        exit_index = entry_index + holding_ticks
        if exit_index >= len(ordered_candles):
            discarded_tail_events += 1
            continue

        exit_candle = ordered_candles[exit_index]
        direction = -1 if point.funding_rate > 0 else 1
        gross_return_pct = direction * (exit_candle.close / entry.close - 1) * 100
        net_return_pct = gross_return_pct - cost_pct
        records.append({
            "funding_time_ms": point.funding_time_ms,
            "funding_rate": point.funding_rate,
            "threshold": threshold,
            "direction": "short" if direction < 0 else "long",
            "entry_time_ms": entry.close_time_ms,
            "entry_price": entry.close,
            "exit_time_ms": exit_candle.close_time_ms,
            "exit_price": exit_candle.close,
            "gross_return_pct": gross_return_pct,
            "net_return_pct": net_return_pct,
        })
        last_exit_time_ms = exit_candle.close_time_ms

    gross_returns = [float(record["gross_return_pct"]) for record in records]
    net_returns = [float(record["net_return_pct"]) for record in records]
    summary = extreme_funding_return_summary(
        net_returns,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    return {
        "lookback_settlements": lookback_settlements,
        "extreme_quantile": extreme_quantile,
        "holding_ticks": holding_ticks,
        "cost_pct": cost_pct,
        "discarded_tail_events": discarded_tail_events,
        "mean_gross_return_pct": (
            sum(gross_returns) / len(gross_returns) if gross_returns else 0.0
        ),
        "median_gross_return_pct": statistics.median(gross_returns) if gross_returns else 0.0,
        "net_returns_pct": net_returns,
        "records": records,
        **summary,
    }


def normalize_funding_slots(
    funding_points: Sequence[FundingPoint],
    *,
    settlement_interval_ms: int = 8 * 3_600_000,
    tolerance_ms: int = 60_000,
) -> dict[int, FundingPoint]:
    """Map exchange timestamps to their nearest standard funding settlement."""
    if settlement_interval_ms < 1 or tolerance_ms < 0:
        raise ValueError("settlement interval must be positive and tolerance non-negative")
    slots: dict[int, FundingPoint] = {}
    offsets: dict[int, int] = {}
    for point in funding_points:
        slot = round(point.funding_time_ms / settlement_interval_ms) * settlement_interval_ms
        offset = abs(point.funding_time_ms - slot)
        if offset > tolerance_ms:
            continue
        if slot not in slots or offset < offsets[slot]:
            slots[slot] = point
            offsets[slot] = offset
    return slots


def funding_relative_strength_report(
    markets: Mapping[str, tuple[Sequence[FundingPoint], Sequence[MarketCandle]]],
    lookback_settlements: int,
    holding_settlements: int,
    *,
    cost_pct: float = 0.14,
    min_market_appearances: int = 10,
    settlement_interval_ms: int = 8 * 3_600_000,
    candle_interval_ms: int = 15 * 60_000,
    funding_tolerance_ms: int = 60_000,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_713,
) -> dict[str, Any]:
    """Audit a market-neutral pair formed from cross-market funding momentum."""
    if len(markets) < 2:
        raise ValueError("at least two markets are required")
    if lookback_settlements < 1 or holding_settlements < 1:
        raise ValueError("lookback and holding settlements must be positive")
    if cost_pct < 0 or min_market_appearances < 0:
        raise ValueError("cost and minimum market appearances must not be negative")
    if candle_interval_ms < 1 or settlement_interval_ms % candle_interval_ms:
        raise ValueError("candle interval must divide the settlement interval")

    funding_by_market = {
        name: normalize_funding_slots(
            funding,
            settlement_interval_ms=settlement_interval_ms,
            tolerance_ms=funding_tolerance_ms,
        )
        for name, (funding, _) in markets.items()
    }
    common_slots = sorted(set.intersection(*(
        set(points) for points in funding_by_market.values()
    )))
    candles_by_market = {
        name: sorted(candles, key=lambda candle: candle.close_time_ms)
        for name, (_, candles) in markets.items()
    }
    candle_times_by_market = {
        name: [candle.close_time_ms for candle in candles]
        for name, candles in candles_by_market.items()
    }
    candle_holding_ticks = (
        holding_settlements * settlement_interval_ms // candle_interval_ms
    )
    appearances = {name: 0 for name in markets}
    records: list[dict[str, Any]] = []
    last_exit_time_ms = -1
    discarded_gap_events = 0
    discarded_overlap_events = 0
    discarded_tail_events = 0

    for index in range(lookback_settlements - 1, len(common_slots)):
        signal_slot = common_slots[index]
        lookback_start = index - lookback_settlements + 1
        expected_lookback_start = signal_slot - (
            lookback_settlements - 1
        ) * settlement_interval_ms
        target_slot = signal_slot + holding_settlements * settlement_interval_ms
        if common_slots[lookback_start] != expected_lookback_start:
            discarded_gap_events += 1
            continue
        if index + holding_settlements >= len(common_slots):
            discarded_tail_events += 1
            continue
        if common_slots[index + holding_settlements] != target_slot:
            discarded_gap_events += 1
            continue

        score_slots = common_slots[lookback_start:index + 1]
        scores = {
            name: sum(
                funding_by_market[name][slot].funding_rate for slot in score_slots
            ) / lookback_settlements
            for name in markets
        }
        ranked = sorted(scores, key=lambda name: (scores[name], name))
        short_market = ranked[0]
        long_market = ranked[-1]
        if scores[long_market] == scores[short_market]:
            continue

        selected = (long_market, short_market)
        entries: dict[str, tuple[int, MarketCandle]] = {}
        exits: dict[str, MarketCandle] = {}
        complete = True
        for name in selected:
            entry_index = bisect_right(candle_times_by_market[name], signal_slot)
            exit_index = entry_index + candle_holding_ticks
            candles = candles_by_market[name]
            if entry_index >= len(candles) or exit_index >= len(candles):
                discarded_tail_events += 1
                complete = False
                break
            entry = candles[entry_index]
            exit_candle = candles[exit_index]
            if entry.close_time_ms <= last_exit_time_ms:
                discarded_overlap_events += 1
                complete = False
                break
            if (
                exit_candle.close_time_ms - entry.close_time_ms
                != holding_settlements * settlement_interval_ms
            ):
                discarded_gap_events += 1
                complete = False
                break
            entries[name] = (entry_index, entry)
            exits[name] = exit_candle
        if not complete:
            continue

        long_entry = entries[long_market][1]
        short_entry = entries[short_market][1]
        long_exit = exits[long_market]
        short_exit = exits[short_market]
        future_slots = common_slots[index + 1:index + holding_settlements + 1]
        long_price_pct = (long_exit.close / long_entry.close - 1) * 100
        short_price_pct = -(short_exit.close / short_entry.close - 1) * 100
        long_funding_pct = -sum(
            funding_by_market[long_market][slot].funding_rate for slot in future_slots
        ) * 100
        short_funding_pct = sum(
            funding_by_market[short_market][slot].funding_rate for slot in future_slots
        ) * 100
        gross_return_pct = 0.5 * (
            long_price_pct
            + short_price_pct
            + long_funding_pct
            + short_funding_pct
        )
        net_return_pct = gross_return_pct - cost_pct
        records.append({
            "signal_slot_ms": signal_slot,
            "scores": scores,
            "long_market": long_market,
            "short_market": short_market,
            "long_entry_time_ms": long_entry.close_time_ms,
            "short_entry_time_ms": short_entry.close_time_ms,
            "exit_time_ms": max(long_exit.close_time_ms, short_exit.close_time_ms),
            "long_price_return_pct": long_price_pct,
            "short_price_return_pct": short_price_pct,
            "long_funding_return_pct": long_funding_pct,
            "short_funding_return_pct": short_funding_pct,
            "gross_return_pct": gross_return_pct,
            "net_return_pct": net_return_pct,
        })
        appearances[long_market] += 1
        appearances[short_market] += 1
        last_exit_time_ms = max(long_exit.close_time_ms, short_exit.close_time_ms)

    net_returns = [float(record["net_return_pct"]) for record in records]
    summary = extreme_funding_return_summary(
        net_returns,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    coverage_admitted = all(
        count >= min_market_appearances for count in appearances.values()
    )
    price_returns = [
        0.5 * (
            float(record["long_price_return_pct"])
            + float(record["short_price_return_pct"])
        )
        for record in records
    ]
    funding_returns = [
        0.5 * (
            float(record["long_funding_return_pct"])
            + float(record["short_funding_return_pct"])
        )
        for record in records
    ]
    gross_returns = [float(record["gross_return_pct"]) for record in records]
    return {
        "lookback_settlements": lookback_settlements,
        "holding_settlements": holding_settlements,
        "holding_days": holding_settlements / 3,
        "cost_pct": cost_pct,
        "common_slots": len(common_slots),
        "discarded_gap_events": discarded_gap_events,
        "discarded_overlap_events": discarded_overlap_events,
        "discarded_tail_events": discarded_tail_events,
        "market_appearances": appearances,
        "min_market_appearances": min_market_appearances,
        "coverage_admitted": coverage_admitted,
        "mean_price_return_pct": (
            sum(price_returns) / len(price_returns) if price_returns else 0.0
        ),
        "mean_funding_return_pct": (
            sum(funding_returns) / len(funding_returns) if funding_returns else 0.0
        ),
        "mean_gross_return_pct": (
            sum(gross_returns) / len(gross_returns) if gross_returns else 0.0
        ),
        "net_returns_pct": net_returns,
        "records": records,
        **summary,
        "statistical_admitted": summary["admitted"],
        "admitted": summary["admitted"] and coverage_admitted,
    }


def estimate(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    cost_pct: float,
    *,
    reversion_pct: float = 0.25,
) -> dict:
    reversions, extensions = excursion_outcomes(closes, a_pct, theta_pct, reversion_pct)
    total = reversions + extensions
    return _estimate_report(
        reversions,
        extensions,
        a_pct,
        theta_pct,
        cost_pct,
        filtered_entries=0,
        entry_candidates=total,
    )


def _estimate_report(
    reversions: int,
    extensions: int,
    a_pct: float,
    theta_pct: float,
    cost_pct: float,
    *,
    filtered_entries: int,
    entry_candidates: int,
    filtered_reversions: int = 0,
    filtered_extensions: int = 0,
    attribution_available: bool = True,
) -> dict[str, Any]:
    total = reversions + extensions
    pi_hat = reversions / total if total else 0.0
    low, high = wilson_interval(reversions, total)
    required = pi_required(a_pct, theta_pct, cost_pct)
    outcomes = [a_pct - cost_pct] * reversions + [-(theta_pct - a_pct) - cost_pct] * extensions
    total_return_pct = sum(outcomes)
    gross_return_pct = reversions * a_pct - extensions * (theta_pct - a_pct)
    fee_drag_pct = total * cost_pct
    filtered_gross_return_pct = (
        filtered_reversions * a_pct - filtered_extensions * (theta_pct - a_pct)
    )
    filtered_net_return_pct = filtered_gross_return_pct - filtered_entries * cost_pct
    return {
        "a_pct": a_pct,
        "theta_pct": theta_pct,
        "cost_pct": cost_pct,
        "excursions": total,
        "reversions": reversions,
        "extensions": extensions,
        "pi_hat": pi_hat,
        "pi_ci_low": low,
        "pi_ci_high": high,
        "pi_required": required,
        # C8 准入：置信下界必须显著高于盈亏平衡线
        "admitted": total >= 30 and low > required,
        "expected_value_pct": expected_value_per_bet(pi_hat, a_pct, theta_pct, cost_pct),
        "total_return_pct": total_return_pct,
        "gross_return_pct": gross_return_pct,
        "fee_drag_pct": fee_drag_pct,
        "break_even_cost_pct": gross_return_pct / total if total and gross_return_pct > 0 else 0.0,
        "filtered_entries": filtered_entries,
        "filtered_reversions": filtered_reversions,
        "filtered_extensions": filtered_extensions,
        "filtered_counterfactual_gross_return_pct": filtered_gross_return_pct,
        "filtered_counterfactual_net_return_pct": filtered_net_return_pct,
        "counterfactual_unfiltered_total_return_pct": total_return_pct + filtered_net_return_pct,
        "gate_avoided_loss_pct": max(0.0, -filtered_net_return_pct),
        "attribution_available": attribution_available,
        "entry_candidates": entry_candidates,
        "trade_frequency": total / entry_candidates if entry_candidates else 0.0,
        "max_drawdown_pct": max_drawdown(outcomes),
    }


def gated_estimate(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    cost_pct: float,
    *,
    gate_config: dict[str, Any] | None = None,
    warmup: Sequence[float] = (),
    reversion_pct: float = 0.25,
) -> dict[str, Any]:
    config = {**DEFAULT_REGIME_CONFIG, **(gate_config or {})}
    config["enabled"] = True
    gate = RegimeGate({"strategy": {"regime_gate": config}})
    state: dict[str, Any] = {}
    for price in warmup:
        if float(price) > 0:
            gate.update(state, float(price))
    regimes = []
    for price in closes:
        gate.update(state, float(price))
        regimes.append(state.get("regime") == RANGE)

    records, candidates = excursion_outcome_records(
        closes,
        a_pct,
        theta_pct,
        reversion_pct,
        allowed_entries=regimes,
    )
    outcomes = [reverted for reverted, allowed in records if allowed]
    filtered_outcomes = [reverted for reverted, allowed in records if not allowed]
    reversions = sum(outcomes)
    extensions = len(outcomes) - reversions
    filtered_reversions = sum(filtered_outcomes)
    filtered_extensions = len(filtered_outcomes) - filtered_reversions
    report = _estimate_report(
        reversions,
        extensions,
        a_pct,
        theta_pct,
        cost_pct,
        filtered_entries=len(filtered_outcomes),
        entry_candidates=candidates,
        filtered_reversions=filtered_reversions,
        filtered_extensions=filtered_extensions,
    )
    report["gate_enabled"] = True
    return report


def excursion_outcome_series(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    reversion_pct: float = 0.25,
    *,
    allowed_entries: Sequence[bool] | None = None,
) -> tuple[list[bool], int, int]:
    records, candidates = excursion_outcome_records(
        closes,
        a_pct,
        theta_pct,
        reversion_pct,
        allowed_entries=allowed_entries,
    )
    outcomes = [reverted for reverted, allowed in records if allowed]
    filtered = sum(1 for _, allowed in records if not allowed)
    return outcomes, filtered, candidates


def excursion_outcome_records(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    reversion_pct: float = 0.25,
    *,
    allowed_entries: Sequence[bool] | None = None,
) -> tuple[list[tuple[bool, bool]], int]:
    if a_pct <= 0 or theta_pct <= a_pct:
        raise ValueError("需要 0 < a < θ")
    records: list[tuple[bool, bool]] = []
    candidates = 0
    anchor: float | None = None
    direction = 0
    active_allowed = True
    for index, raw_price in enumerate(closes):
        price = float(raw_price)
        if price <= 0:
            continue
        if anchor is None:
            anchor = price
            continue
        move_pct = (price / anchor - 1) * 100
        if direction == 0:
            if abs(move_pct) >= a_pct:
                direction = 1 if move_pct > 0 else -1
                active_allowed = allowed_entries is None or bool(allowed_entries[index])
                candidates += 1
            continue
        directed = move_pct * direction
        if directed >= theta_pct or directed <= reversion_pct:
            records.append((directed <= reversion_pct, active_allowed))
            anchor = price
            direction = 0
            active_allowed = True
    return records, candidates


def max_drawdown(outcomes: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for outcome in outcomes:
        equity += float(outcome)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def default_gate_config_grid() -> list[dict[str, Any]]:
    return [
        {
            "window": window,
            "confirm_ticks": confirm_ticks,
            "range_efficiency_ratio": range_er,
            "trend_efficiency_ratio": trend_er,
        }
        for window in (24, 48, 96)
        for confirm_ticks in (1, 3)
        for range_er, trend_er in ((0.25, 0.55), (0.35, 0.65), (0.45, 0.75))
    ]


def select_gate_config(
    closes: Sequence[float],
    a_pct: float,
    theta_pct: float,
    cost_pct: float,
    gate_configs: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not gate_configs:
        raise ValueError("gate_configs must not be empty")
    baseline = estimate(closes, a_pct, theta_pct, cost_pct)
    minimum_trades = max(5, math.ceil(int(baseline["excursions"]) * 0.25))
    candidates = []
    for raw_config in gate_configs:
        config = {**DEFAULT_REGIME_CONFIG, **raw_config, "enabled": True}
        report = gated_estimate(closes, a_pct, theta_pct, cost_pct, gate_config=config)
        report["selection_eligible"] = report["excursions"] >= minimum_trades
        report["confidence_margin"] = report["pi_ci_low"] - report["pi_required"]
        candidates.append((config, report))
    eligible = [candidate for candidate in candidates if candidate[1]["selection_eligible"]]
    pool = eligible or candidates
    selected_config, selected_report = max(
        pool,
        key=lambda candidate: (
            candidate[1]["confidence_margin"],
            candidate[1]["expected_value_pct"],
            candidate[1]["excursions"],
        ),
    )
    selected_report["minimum_selection_trades"] = minimum_trades
    selected_report["eligible_configs"] = len(eligible)
    selected_report["evaluated_configs"] = len(candidates)
    return selected_config, selected_report


def walk_forward_compare(
    closes: Sequence[float],
    a_grid: Sequence[float],
    theta_grid: Sequence[float],
    cost_pct: float,
    *,
    train_size: int,
    validation_size: int,
    step: int | None = None,
    gate_config: dict[str, Any] | None = None,
    gate_config_grid: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if train_size < 30 or validation_size < 10:
        raise ValueError("train_size must be >= 30 and validation_size >= 10")
    step = int(step or validation_size)
    folds = []
    start = 0
    while start + train_size + validation_size <= len(closes):
        train = closes[start:start + train_size]
        validation = closes[start + train_size:start + train_size + validation_size]
        candidates = geometry_scan(train, a_grid, theta_grid, cost_pct)
        selected = next((row for row in candidates if row["admitted"]), candidates[0])
        off = estimate(validation, selected["a_pct"], selected["theta_pct"], cost_pct)
        selected_gate_config = {**DEFAULT_REGIME_CONFIG, **(gate_config or {})}
        gate_training_report = None
        if gate_config_grid is not None:
            selected_gate_config, gate_training_report = select_gate_config(
                train,
                selected["a_pct"],
                selected["theta_pct"],
                cost_pct,
                gate_config_grid,
            )
        warmup_size = max(int(selected_gate_config.get("window", DEFAULT_REGIME_CONFIG["window"])), 3)
        on = gated_estimate(
            validation,
            selected["a_pct"],
            selected["theta_pct"],
            cost_pct,
            gate_config=selected_gate_config,
            warmup=train[-warmup_size:],
        )
        gate_qualified = gate_training_report is None or bool(gate_training_report["admitted"])
        deploy = on if gate_qualified else _estimate_report(
            0,
            0,
            selected["a_pct"],
            selected["theta_pct"],
            cost_pct,
            filtered_entries=int(off["excursions"]),
            entry_candidates=int(off["excursions"]),
            attribution_available=False,
        )
        folds.append({
            "fold": len(folds) + 1,
            "train_start": start,
            "train_end": start + train_size,
            "validation_end": start + train_size + validation_size,
            "selected_a_pct": selected["a_pct"],
            "selected_theta_pct": selected["theta_pct"],
            "train": selected,
            "selected_gate_config": selected_gate_config,
            "gate_training": gate_training_report,
            "gate_qualified": gate_qualified,
            "gate_off": off,
            "gate_on": on,
            "gate_deploy": deploy,
        })
        start += step
    if not folds:
        raise ValueError("not enough closes for one walk-forward fold")
    return {
        "train_size": train_size,
        "validation_size": validation_size,
        "step": step,
        "gate_tuning_enabled": gate_config_grid is not None,
        "folds": folds,
        "aggregate": {
            "gate_off": aggregate_reports([fold["gate_off"] for fold in folds], cost_pct),
            "gate_on": aggregate_reports([fold["gate_on"] for fold in folds], cost_pct),
            "gate_deploy": aggregate_reports([fold["gate_deploy"] for fold in folds], cost_pct),
        },
    }


def aggregate_reports(reports: Sequence[dict[str, Any]], cost_pct: float) -> dict[str, Any]:
    reversions = sum(int(report["reversions"]) for report in reports)
    extensions = sum(int(report["extensions"]) for report in reports)
    total = reversions + extensions
    if not reports:
        return {}
    candidates = sum(int(report.get("entry_candidates", 0)) for report in reports)
    filtered = sum(int(report.get("filtered_entries", 0)) for report in reports)
    total_return = sum(float(report["total_return_pct"]) for report in reports)
    gross_return = sum(float(report.get("gross_return_pct", 0.0)) for report in reports)
    fee_drag = sum(float(report.get("fee_drag_pct", 0.0)) for report in reports)
    filtered_reversions = sum(int(report.get("filtered_reversions", 0)) for report in reports)
    filtered_extensions = sum(int(report.get("filtered_extensions", 0)) for report in reports)
    filtered_counterfactual_net = sum(
        float(report.get("filtered_counterfactual_net_return_pct", 0.0)) for report in reports
    )
    pi_hat = reversions / total if total else 0.0
    low, high = wilson_interval(reversions, total)
    required = (
        sum(float(report["pi_required"]) * int(report["excursions"]) for report in reports) / total
        if total
        else 0.0
    )
    unique_geometries = sorted({
        (float(report["a_pct"]), float(report["theta_pct"]))
        for report in reports
    })
    return {
        "folds": len(reports),
        "cost_pct": cost_pct,
        "geometries": [
            {"a_pct": a_pct, "theta_pct": theta_pct}
            for a_pct, theta_pct in unique_geometries
        ],
        "excursions": total,
        "reversions": reversions,
        "extensions": extensions,
        "pi_hat": pi_hat,
        "pi_ci_low": low,
        "pi_ci_high": high,
        "pi_required_weighted": required,
        "admitted": total >= 30 and low > required,
        "expected_value_pct": total_return / total if total else 0.0,
        "total_return_pct": total_return,
        "gross_return_pct": gross_return,
        "fee_drag_pct": fee_drag,
        "break_even_cost_pct": gross_return / total if total and gross_return > 0 else 0.0,
        "filtered_entries": filtered,
        "filtered_reversions": filtered_reversions,
        "filtered_extensions": filtered_extensions,
        "filtered_counterfactual_net_return_pct": filtered_counterfactual_net,
        "counterfactual_unfiltered_total_return_pct": total_return + filtered_counterfactual_net,
        "gate_avoided_loss_pct": max(0.0, -filtered_counterfactual_net),
        "attribution_available": all(bool(report.get("attribution_available", False)) for report in reports),
        "entry_candidates": candidates,
        "trade_frequency": total / candidates if candidates else 0.0,
        "profitable_folds": sum(1 for report in reports if report["expected_value_pct"] > 0),
        "worst_fold_drawdown_pct": max(float(report["max_drawdown_pct"]) for report in reports),
        "conservative_drawdown_bound_pct": sum(float(report["max_drawdown_pct"]) for report in reports),
    }


def portfolio_calibration_summary(
    market_results: Sequence[dict[str, Any]],
    cost_pct: float,
    *,
    comparison: str = "gate_on",
) -> dict[str, Any]:
    if comparison not in {"gate_on", "gate_off", "gate_deploy"}:
        raise ValueError("comparison must be gate_on, gate_off, or gate_deploy")
    reports = [
        fold[comparison]
        for market in market_results
        for fold in market["result"]["folds"]
    ]
    aggregate = aggregate_reports(reports, cost_pct)
    profitable_markets = sum(
        1
        for market in market_results
        if market["result"]["aggregate"][comparison]["expected_value_pct"] > 0
    )
    market_count = len(market_results)
    required_profitable_markets = market_count // 2 + 1
    aggregate.update({
        "comparison": comparison,
        "markets": market_count,
        "profitable_markets": profitable_markets,
        "required_profitable_markets": required_profitable_markets,
        "stage_admitted": bool(
            aggregate.get("admitted")
            and aggregate.get("expected_value_pct", 0.0) > 0
            and profitable_markets >= required_profitable_markets
        ),
    })
    return aggregate


def geometry_scan(
    closes: Sequence[float],
    a_grid: Sequence[float],
    theta_grid: Sequence[float],
    cost_pct: float,
) -> list[dict]:
    """(a, θ) 几何扫描：对每个组合估计 π̂ 与单注期望，供选择最优触发几何。"""
    rows = []
    for a_pct in a_grid:
        for theta_pct in theta_grid:
            if theta_pct <= a_pct:
                continue
            rows.append(estimate(closes, a_pct, theta_pct, cost_pct))
    return sorted(rows, key=lambda row: row["expected_value_pct"], reverse=True)
