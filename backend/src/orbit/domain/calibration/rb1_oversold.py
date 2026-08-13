from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint
from orbit.domain.calibration.r0_shortline import (
    ShortlineCandle, oversold_direction, simple_atr, summarize_events,
)

INTERVAL_MS = 15 * 60 * 1000
EXPECTED_IDS = ("ST-A__EX-A", "ST-A__EX-B", "ST-B__EX-A", "ST-B__EX-B")


def frozen_candidates(contract: Mapping[str, Any]) -> list[dict[str, str]]:
    rows = [dict(item) for item in contract["candidates"]]
    ids = tuple(item.get("id") for item in rows)
    if len(rows) != 4 or set(ids) != set(EXPECTED_IDS) or len(set(ids)) != 4:
        raise ValueError("RB-1 frozen grid must contain exactly the four registered candidates")
    if int(contract["discipline"]["grid_size_max"]) != 4:
        raise ValueError("RB-1 grid ceiling changed")
    return rows


def detect_signals(
    candles: Sequence[ShortlineCandle], *, start_ms: int, end_ms: int,
    lookback: int = 16, drop: float = .10, holding: int = 32, atr_period: int = 14,
) -> list[int]:
    ordered = _ordered(candles)
    result, next_index = [], 0
    history = max(lookback, atr_period + 1)
    for index, candle in enumerate(ordered):
        if index < next_index or index < history or candle.close_time_ms < start_ms:
            continue
        if not oversold_direction(ordered, index, return_lookback=lookback, minimum_drop_fraction=drop):
            continue
        exit_index = index + 1 + holding
        if exit_index >= len(ordered):
            continue
        required = ordered[index - history:exit_index + 1]
        if not _contiguous(required) or ordered[exit_index].open_time_ms > end_ms:
            continue
        result.append(index)
        next_index = exit_index
    return result


def simulate_candidate_events(
    symbol: str, candles: Sequence[ShortlineCandle], funding: Sequence[FundingPoint],
    signal_indices: Sequence[int], candidate_id: str, *,
    tier_at: Callable[[str, int], str | None], costs: Mapping[str, float],
    end_ms: int, diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None = None,
) -> list[dict[str, Any]]:
    if candidate_id not in EXPECTED_IDS:
        raise ValueError("unregistered RB-1 candidate")
    ordered = _ordered(candles)
    funding = sorted(funding, key=lambda item: item.funding_time_ms)
    funding_times = [item.funding_time_ms for item in funding]
    events = []
    for signal_index in signal_indices:
        signal, entry_index = ordered[signal_index], signal_index + 1
        time_index = entry_index + 32
        entry = ordered[entry_index]
        tier = tier_at(symbol, signal.close_time_ms)
        if tier not in costs:
            continue
        atr = simple_atr(ordered, signal_index, 14)
        initial_stop = (
            entry.open - 3 * atr if candidate_id.startswith("ST-A")
            else signal.low - .5 * atr
        )
        if initial_stop >= entry.open or atr <= 0:
            continue
        result = _run_exit(
            ordered, entry_index, time_index, entry.open, initial_stop, atr,
            exit_b=candidate_id.endswith("EX-B"),
        )
        legs = result["legs"]
        funding_return = 0.0
        for leg in legs:
            left = bisect_right(funding_times, entry.open_time_ms)
            right = bisect_right(funding_times, int(leg["exit_time_ms"]))
            funding_return -= float(leg["weight"]) * sum(
                point.funding_rate for point in funding[left:right]
            )
        price_return = sum(
            float(leg["weight"]) * (float(leg["exit_price"]) / entry.open - 1)
            for leg in legs
        )
        cost_pct = float(costs[tier])
        event = {
            "symbol": symbol, "candidate_id": candidate_id,
            "definition_id": "S1_DROP_STABILIZATION",
            "signal_time_ms": signal.close_time_ms, "entry_time_ms": entry.open_time_ms,
            "exit_time_ms": max(int(leg["exit_time_ms"]) for leg in legs),
            "entry_day_utc": datetime.fromtimestamp(entry.open_time_ms / 1000, tz=timezone.utc).date().isoformat(),
            "entry_year_utc": datetime.fromtimestamp(entry.open_time_ms / 1000, tz=timezone.utc).year,
            "direction": "LONG", "tier": tier, "entry_price": entry.open,
            "signal_candle_low": signal.low, "atr14": atr,
            "initial_stop_price": initial_stop, "initial_r": entry.open - initial_stop,
            "exit_reason": result["exit_reason"], "legs": legs,
            "trailing_stop_history": result["trailing_stop_history"],
            "price_return_pct": price_return * 100,
            "funding_return_pct": funding_return * 100,
            "cost_pct": cost_pct,
            "net_return_pct": 100 * (price_return + funding_return) - cost_pct,
        }
        if diagnostics_at:
            detail = diagnostics_at(symbol, signal.close_time_ms)
            if detail:
                event.update(detail)
        if event["exit_time_ms"] <= end_ms:
            events.append(event)
    return events


def summarize_candidate(events: Sequence[Mapping[str, Any]], samples: int, seed: int) -> dict[str, Any]:
    summary = summarize_events(events, bootstrap_samples=samples, bootstrap_seed=seed)
    years = [float(row["mean_net_return_pct"]) for row in summary["by_year"].values()]
    summary["worst_calendar_year_mean_net_return_pct"] = min(years) if years else 0.0
    return summary


def _run_exit(candles, entry_index, time_index, entry_price, initial_stop, atr, *, exit_b):
    stop, active, half_closed = initial_stop, False, False
    legs, stop_history = [], [{"effective_from_index": entry_index, "stop_price": stop}]
    remaining = 1.0
    r_value = entry_price - initial_stop
    trigger = entry_price + (1.5 if exit_b else 1.0) * r_value
    final_reason = "TIME"
    for index in range(entry_index, time_index + 1):
        candle = candles[index]
        touched = candle.low <= stop
        if touched:
            price = candle.open if candle.open < stop else stop
            reason = "STOP_GAP" if candle.open < stop else "STOP"
            legs.append({"weight": remaining, "exit_price": price, "exit_time_ms": candle.open_time_ms, "reason": reason})
            final_reason = reason
            break
        if index == time_index:
            legs.append({"weight": remaining, "exit_price": candle.open, "exit_time_ms": candle.open_time_ms, "reason": "TIME"})
            break
        if not active and candle.high >= trigger:
            active = True
            if exit_b:
                price = max(candle.open, trigger) if candle.open >= trigger else trigger
                legs.append({"weight": .5, "exit_price": price, "exit_time_ms": candle.open_time_ms, "reason": "HALF_AT_1_5R"})
                remaining, half_closed = .5, True
        if active:
            current_atr = simple_atr(candles, index, 14)
            updated = max(stop, candle.close - 2 * current_atr)
            if not exit_b:
                updated = max(updated, entry_price)
            if updated > stop:
                stop = updated
                stop_history.append({"effective_from_index": index + 1, "stop_price": stop})
    if not legs:
        raise ValueError("RB-1 exit simulation produced no exit")
    return {"legs": legs, "exit_reason": final_reason, "trailing_stop_history": stop_history, "half_closed": half_closed}


def _ordered(candles):
    return sorted(candles, key=lambda item: item.open_time_ms)


def _contiguous(candles):
    return all(right.open_time_ms - left.open_time_ms == INTERVAL_MS for left, right in zip(candles, candles[1:]))
