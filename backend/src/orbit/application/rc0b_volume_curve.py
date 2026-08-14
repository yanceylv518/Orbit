from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import math
import statistics
from typing import Any, Mapping, Sequence


DAY_MS = 86_400_000


def breakout_shape(
    candles: Sequence[Any], signal_index: int, direction: str
) -> dict[str, Any] | None:
    """Measure frozen breakout shape using the completed signal candle only."""
    if signal_index < 96:
        return None
    signal = candles[signal_index]
    prior_volumes = [float(row.quote_volume) for row in candles[signal_index - 96 : signal_index]]
    volume_baseline = statistics.median(prior_volumes)
    relative_volume = float(signal.quote_volume) / volume_baseline if volume_baseline > 0 else None
    breaks: dict[str, bool] = {}
    for channel in (32, 96, 288):
        if signal_index < channel:
            breaks[str(channel)] = False
            continue
        history = candles[signal_index - channel : signal_index]
        if direction == "LONG":
            breaks[str(channel)] = float(signal.close) > max(float(row.high) for row in history)
        elif direction == "SHORT":
            breaks[str(channel)] = float(signal.close) < min(float(row.low) for row in history)
        else:
            raise ValueError(f"unsupported direction: {direction}")
    return {"relative_quote_volume": relative_volume, "breaks_channel": breaks}


def select_combination(
    events: Sequence[Mapping[str, Any]],
    *,
    liquidity_threshold_usdt: int,
    channel_lookback_candles: int | None = None,
    minimum_relative_quote_volume: float | None = None,
) -> list[dict[str, Any]]:
    eligibility_key = f"eligible_{liquidity_threshold_usdt}"
    selected = []
    for source in events:
        row = dict(source)
        if not bool(row.get(eligibility_key)):
            continue
        if channel_lookback_candles is not None:
            if not bool(row.get(f"breaks_channel_{channel_lookback_candles}")):
                continue
            relative_volume = row.get("relative_quote_volume")
            if relative_volume is None or float(relative_volume) < float(minimum_relative_quote_volume):
                continue
        selected.append(row)
    return selected


def frequency_summary(
    events: Sequence[Mapping[str, Any]], *, start_day_ms: int, end_day_ms: int
) -> dict[str, Any]:
    if end_day_ms < start_day_ms:
        raise ValueError("end day precedes start day")
    day_keys = [
        _day_key(timestamp)
        for timestamp in range(start_day_ms, end_day_ms + 1, DAY_MS)
    ]
    month_keys = _month_keys(start_day_ms, end_day_ms)
    daily = Counter(_day_key(int(row["signal_time_ms"])) for row in events)
    monthly = Counter(_month_key(int(row["signal_time_ms"])) for row in events)
    day_values = [daily[key] for key in day_keys]
    month_values = [monthly[key] for key in month_keys]
    return {
        "event_count": len(events),
        "calendar_day_count": len(day_keys),
        "calendar_month_count": len(month_keys),
        "mean_signals_per_day": statistics.fmean(day_values) if day_values else 0.0,
        "mean_signals_per_month": statistics.fmean(month_values) if month_values else 0.0,
        "monthly_p90": quantile(month_values, 0.90),
        "maximum_signals_per_day": max(day_values, default=0),
        "maximum_signals_per_month": max(month_values, default=0),
        "by_day": dict(zip(day_keys, day_values)),
        "by_month": dict(zip(month_keys, month_values)),
    }


def large_opportunity_retention(
    source_events: Sequence[Mapping[str, Any]], selected_events: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    source_labeled = [row for row in source_events if row.get("large_opportunity") is not None]
    selected_labeled = [row for row in selected_events if row.get("large_opportunity") is not None]
    source_large = sum(bool(row["large_opportunity"]) for row in source_labeled)
    selected_large = sum(bool(row["large_opportunity"]) for row in selected_labeled)
    return {
        "source_labeled_event_count": len(source_labeled),
        "selected_labeled_event_count": len(selected_labeled),
        "source_large_opportunity_count": source_large,
        "retained_large_opportunity_count": selected_large,
        "retained_large_opportunity_fraction": selected_large / source_large if source_large else None,
    }


def distribution_summary(values: Sequence[int | float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "mean": statistics.fmean(ordered) if ordered else 0.0,
        "minimum": ordered[0] if ordered else 0,
        "p10": quantile(ordered, 0.10),
        "p25": quantile(ordered, 0.25),
        "p50": quantile(ordered, 0.50),
        "p75": quantile(ordered, 0.75),
        "p90": quantile(ordered, 0.90),
        "p99": quantile(ordered, 0.99),
        "maximum": ordered[-1] if ordered else 0,
    }


def quantile(values: Sequence[int | float], level: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * level
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower]) + (float(ordered[upper]) - float(ordered[lower])) * (position - lower)


def _day_key(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _month_key(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m")


def _month_keys(start_ms: int, end_ms: int) -> list[str]:
    start = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
    year, month = start.year, start.month
    result = []
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result
