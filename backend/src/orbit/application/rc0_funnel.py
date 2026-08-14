from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

FILTERS = ("EFFICIENCY_RATIO", "TREND_STRENGTH", "WICKINESS", "COMBINED")


def signal_features(candles, signal_index: int, direction: str, atr14: float, window: int) -> dict[str, float] | None:
    if signal_index < window or atr14 <= 0:
        return None
    closes = [float(candles[index].close) for index in range(signal_index - window, signal_index + 1)]
    path_length = sum(abs(right - left) for left, right in zip(closes, closes[1:]))
    efficiency_ratio = abs(closes[-1] - closes[0]) / path_length if path_length > 0 else 0.0
    direction_sign = 1.0 if direction == "LONG" else -1.0
    trend_strength = direction_sign * (closes[-1] - closes[0]) / float(atr14)
    wickiness_values = []
    for candle in candles[signal_index - window + 1 : signal_index + 1]:
        upper = max(0.0, float(candle.high) - max(float(candle.open), float(candle.close)))
        lower = max(0.0, min(float(candle.open), float(candle.close)) - float(candle.low))
        body = max(abs(float(candle.close) - float(candle.open)), abs(float(candle.close)) * 1e-6)
        wickiness_values.append((upper + lower) / body)
    return {
        "efficiency_ratio": efficiency_ratio,
        "trend_strength": trend_strength,
        "wickiness": statistics.fmean(wickiness_values),
    }


def funnel_curve(
    events: Sequence[Mapping[str, Any]],
    filter_name: str,
    retained_fractions: Sequence[float],
    *,
    workload_minimum: float = 10,
    workload_maximum: float = 30,
) -> dict[str, Any]:
    if filter_name not in FILTERS:
        raise ValueError(f"unsupported filter: {filter_name}")
    rows = [dict(event) for event in events]
    month_keys = _month_range(rows)
    total_large = sum(bool(row["large_opportunity"]) for row in rows)
    base_precision = total_large / len(rows) if rows else None
    points = [
        _curve_point(rows, filter_name, float(fraction), month_keys, total_large, base_precision)
        for fraction in retained_fractions
    ]
    matching = [
        point
        for point in points
        if workload_minimum <= point["monthly_remaining_signals"]["mean"] <= workload_maximum
    ]
    nearest = None
    if points and not matching:
        nearest = min(
            points,
            key=lambda point: _distance_to_band(
                point["monthly_remaining_signals"]["mean"], workload_minimum, workload_maximum
            ),
        )
    return {
        "filter": filter_name,
        "eligible_event_count": len(rows),
        "large_opportunity_count": total_large,
        "base_large_opportunity_precision": base_precision,
        "curve": points,
        "usable_workload_band": {
            "minimum_mean_signals_per_month": workload_minimum,
            "maximum_mean_signals_per_month": workload_maximum,
            "matching_points": matching,
            "nearest_point_when_no_match": nearest,
        },
    }


def _curve_point(rows, filter_name, fraction, month_keys, total_large, base_precision):
    selected, thresholds = _select(rows, filter_name, fraction)
    selected_large = sum(bool(row["large_opportunity"]) for row in selected)
    precision = selected_large / len(selected) if selected else None
    return {
        "requested_marginal_retained_fraction": fraction,
        "actual_retained_event_count": len(selected),
        "actual_retained_fraction": len(selected) / len(rows) if rows else 0.0,
        "exploratory_boundary": thresholds,
        "monthly_remaining_signals": _monthly_summary(selected, month_keys),
        "retained_large_opportunity_count": selected_large,
        "large_opportunity_recall": selected_large / total_large if total_large else None,
        "large_opportunity_precision": precision,
        "enrichment": precision / base_precision if precision is not None and base_precision else None,
    }


def _select(rows, filter_name, fraction):
    count = min(len(rows), max(1, math.ceil(len(rows) * fraction))) if rows else 0
    if filter_name == "COMBINED":
        selections = {
            name: _rank(rows, name)[:count]
            for name in ("EFFICIENCY_RATIO", "TREND_STRENGTH", "WICKINESS")
        }
        identities = [
            {_identity(row) for row in selected}
            for selected in selections.values()
        ]
        retained_ids = set.intersection(*identities) if identities else set()
        selected = [row for row in rows if _identity(row) in retained_ids]
        boundaries = {
            name: _feature_value(selected_rows[-1], name) if selected_rows else None
            for name, selected_rows in selections.items()
        }
        return selected, boundaries
    ranked = _rank(rows, filter_name)
    selected = ranked[:count]
    boundary = _feature_value(selected[-1], filter_name) if selected else None
    return selected, {filter_name: boundary}


def _rank(rows, filter_name):
    reverse_value = filter_name in ("EFFICIENCY_RATIO", "TREND_STRENGTH")
    return sorted(
        rows,
        key=lambda row: (
            -_feature_value(row, filter_name) if reverse_value else _feature_value(row, filter_name),
            int(row["signal_time_ms"]),
            str(row["symbol"]),
            str(row["direction"]),
        ),
    )


def _feature_value(row, filter_name):
    return float(
        row[
            {
                "EFFICIENCY_RATIO": "efficiency_ratio",
                "TREND_STRENGTH": "trend_strength",
                "WICKINESS": "wickiness",
            }[filter_name]
        ]
    )


def _identity(row):
    return (str(row["family_id"]), str(row["symbol"]), int(row["signal_time_ms"]), str(row["direction"]))


def _month_range(rows):
    if not rows:
        return []
    start = datetime.fromtimestamp(min(int(row["signal_time_ms"]) for row in rows) / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(max(int(row["signal_time_ms"]) for row in rows) / 1000, tz=timezone.utc)
    year, month = start.year, start.month
    result = []
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        month = month + 1
        if month == 13:
            year, month = year + 1, 1
    return result


def _monthly_summary(rows, month_keys):
    counts = {month: 0 for month in month_keys}
    for row in rows:
        month = datetime.fromtimestamp(int(row["signal_time_ms"]) / 1000, tz=timezone.utc).strftime("%Y-%m")
        counts[month] += 1
    values = sorted(counts.values())
    return {
        "month_count": len(month_keys),
        "mean": statistics.fmean(values) if values else 0.0,
        "p50": _quantile(values, 0.5) if values else 0.0,
        "p90": _quantile(values, 0.9) if values else 0.0,
        "maximum": max(values) if values else 0,
        "by_month": counts,
    }


def _quantile(values, level):
    position = (len(values) - 1) * level
    lower, upper = math.floor(position), math.ceil(position)
    return values[lower] if lower == upper else values[lower] + (values[upper] - values[lower]) * (position - lower)


def _distance_to_band(value, minimum, maximum):
    if value < minimum:
        return minimum - value
    if value > maximum:
        return value - maximum
    return 0.0
