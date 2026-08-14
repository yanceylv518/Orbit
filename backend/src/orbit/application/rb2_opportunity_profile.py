from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import math
import statistics
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.r0_shortline import ShortlineCandle, simple_atr

QUANTILES = (.50, .75, .90, .95, .99)
TOUCH_LEVELS = (1, 2, 3, 5, 10)
TAILS = (.01, .05, .10, .20)
NUMERIC_FEATURES = ("drop_depth_pct", "relative_quote_volume", "btc_same_window_return_pct", "utc_hour", "atr_relative_pct")
CATEGORICAL_FEATURES = ("volume_trend_3d", "tier", "listing_age")


def observable_features(candles: Sequence[ShortlineCandle], signal_index: int, lookback: int, btc_return_pct: float | None, event: Mapping[str, Any]) -> dict[str, Any]:
    signal = candles[signal_index]
    reference = candles[signal_index - lookback].close
    volumes = [row.quote_volume for row in candles[signal_index - lookback:signal_index]]
    relative_volume = signal.quote_volume / statistics.median(volumes) if volumes and statistics.median(volumes) > 0 else None
    atr = simple_atr(candles, signal_index, 14)
    return {
        "drop_depth_pct": (1 - signal.close / reference) * 100,
        "relative_quote_volume": relative_volume,
        "volume_trend_3d": event["volume_trend_3d"],
        "btc_same_window_return_pct": btc_return_pct,
        "tier": event["tier"],
        "utc_hour": datetime.fromtimestamp(signal.close_time_ms / 1000, tz=timezone.utc).hour,
        "listing_age": event["listing_age"],
        "atr_relative_pct": atr / float(event["entry_price"]) * 100,
    }


def add_opportunity_metrics(event: Mapping[str, Any], candles: Sequence[ShortlineCandle], *, initial_r: float) -> dict[str, Any]:
    row = dict(event)
    if initial_r <= 0:
        raise ValueError("initial risk R must be positive")
    by_open = {c.open_time_ms: index for index, c in enumerate(candles)}
    start = by_open[int(row["entry_time_ms"])]
    end = by_open[int(row["exit_time_ms"])]
    observed = list(candles[start:end + 1])
    if row.get("exit_reason") in {"STOP", "STOP_GAP"} and observed:
        favorable_prices = [item.high for item in observed[:-1]] + [observed[-1].open]
    else:
        favorable_prices = [item.high for item in observed]
    mfe = max(0.0, max(favorable_prices) - float(row["entry_price"]))
    row["initial_r"] = initial_r
    row["mfe_r"] = mfe / initial_r
    row["final_return_r"] = (float(row["net_return_pct"]) / 100 * float(row["entry_price"])) / initial_r
    return row


def profile_events(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = sorted((dict(item) for item in events), key=lambda x: (int(x["signal_time_ms"]), str(x["symbol"])))
    if not rows:
        raise ValueError("RB-2 profile requires events")
    ranked = sorted(rows, key=lambda x: (float(x["net_return_pct"]), int(x["signal_time_ms"]), str(x["symbol"])))
    cut = max(1, math.ceil(len(rows) * .10))
    for index, row in enumerate(ranked):
        row["outcome_group"] = "BOTTOM_10_PCT" if index < cut else ("TOP_10_PCT" if index >= len(rows) - cut else "MIDDLE_80_PCT")
    return {
        "event_count": len(rows),
        "r_multiple_distribution": _r_distribution(rows),
        "tail_contribution": _tail(rows),
        "selection_effort_curve": _selection_effort(rows),
        "frequency": _frequency(rows),
        "identifiability": _identifiability(ranked),
    }


def identifiability_by_metric(events: Sequence[Mapping[str, Any]], metric: str) -> dict[str, Any]:
    rows = sorted((dict(item) for item in events), key=lambda x: (float(x[metric]), int(x["signal_time_ms"]), str(x["symbol"])))
    cut = max(1, math.ceil(len(rows) * .10))
    for index, row in enumerate(rows):
        row["outcome_group"] = "BOTTOM_10_PCT" if index < cut else ("TOP_10_PCT" if index >= len(rows) - cut else "MIDDLE_80_PCT")
    result = _identifiability(rows)
    result["ranking_metric"] = metric
    result["multiple_testing_note"] = "TRAINING_SLICE_REQUIRES_INDEPENDENT_VALIDATION"
    return result


def _r_distribution(rows):
    mfe, final = sorted(float(x["mfe_r"]) for x in rows), sorted(float(x["final_return_r"]) for x in rows)
    edges = (0, .5, 1, 2, 3, 5, 10)
    return {
        "mfe_r_quantiles": {f"p{int(q*100)}": _quantile(mfe, q) for q in QUANTILES},
        "final_return_r_quantiles": {f"p{int(q*100)}": _quantile(final, q) for q in QUANTILES},
        "mfe_touch_rate": {f"gte_{level}r": sum(value >= level for value in mfe) / len(mfe) for level in TOUCH_LEVELS},
        "mfe_r_histogram": _histogram(mfe, edges),
        "final_return_r_histogram": _histogram(final, (-math.inf, -2, -1, 0, .5, 1, 2, 3, 5, 10, math.inf)),
    }


def _tail(rows):
    ordered = sorted(rows, key=lambda x: float(x["net_return_pct"]), reverse=True)
    profit_pool = sum(max(0.0, float(x["net_return_pct"])) for x in rows)
    contributions = {}
    for fraction in TAILS:
        count = max(1, math.ceil(len(rows) * fraction))
        contributions[f"top_{int(fraction*100)}_pct"] = sum(max(0.0, float(x["net_return_pct"])) for x in ordered[:count]) / profit_pool if profit_pool else None
    removed = ordered[math.ceil(len(rows) * .10):]
    mean = statistics.fmean(float(x["net_return_pct"]) for x in removed)
    return {"denominator": "SUM_OF_POSITIVE_NET_RETURNS", "profit_pool_pct_points": profit_pool, "contribution_share": contributions, "mean_after_removing_top_10_pct": mean, "sign_after_removing_top_10_pct": "POSITIVE" if mean > 0 else ("NEGATIVE" if mean < 0 else "ZERO")}


def _selection_effort(rows):
    ordered = sorted(float(x["net_return_pct"]) for x in rows)
    fractions = (.05, .10, .15, .20, .30, .40, .50, .60)
    removal, retention = [], []
    minimum = None
    for fraction in fractions:
        removed = math.ceil(len(ordered) * fraction)
        kept = ordered[removed:]
        mean = statistics.fmean(kept)
        removal.append({"removed_worst_fraction": fraction, "remaining_event_count": len(kept), "remaining_mean_net_return_pct": mean})
        if minimum is None and mean > .3:
            minimum = fraction
        count = max(1, math.ceil(len(ordered) * fraction))
        best = ordered[-count:]
        retention.append({"retained_best_fraction": fraction, "retained_event_count": len(best), "retained_mean_net_return_pct": statistics.fmean(best)})
    return {"hindsight_only_difficulty_lower_bound": True, "descriptive_target_mean_pct": .3, "minimum_worst_removal_fraction_to_exceed_target": minimum, "remove_worst_curve": removal, "retain_best_curve": retention}


def _frequency(rows):
    weeks, months, days, symbols = Counter(), Counter(), Counter(), Counter()
    for row in rows:
        dt = datetime.fromtimestamp(int(row["signal_time_ms"]) / 1000, tz=timezone.utc)
        iso = dt.isocalendar()
        weeks[f"{iso.year}-W{iso.week:02d}"] += 1
        months[dt.strftime("%Y-%m")] += 1
        days[dt.date().isoformat()] += 1
        symbols[str(row["symbol"])] += 1
    return {"by_month": dict(sorted(months.items())), "by_week": dict(sorted(weeks.items())), "daily_mean_on_calendar_span": len(rows) / ((max(days) and (datetime.fromisoformat(max(days)) - datetime.fromisoformat(min(days))).days + 1)), "maximum_in_one_day": max(days.values()), "by_symbol": dict(sorted(symbols.items(), key=lambda x: (-x[1], x[0]))), "top_10_symbols_share": sum(value for _, value in symbols.most_common(10)) / len(rows)}


def _identifiability(rows):
    groups = {name: [x for x in rows if x["outcome_group"] == name] for name in ("TOP_10_PCT", "MIDDLE_80_PCT", "BOTTOM_10_PCT")}
    features = {}
    for feature in NUMERIC_FEATURES:
        summaries = {name: _numeric([x["features"].get(feature) for x in group]) for name, group in groups.items()}
        features[feature] = {"type": "NUMERIC", "groups": summaries, "top_minus_bottom_mean": _difference(summaries)}
    for feature in CATEGORICAL_FEATURES:
        categories = sorted({str(x["features"].get(feature)) for x in rows})
        distributions = {name: {cat: sum(str(x["features"].get(feature)) == cat for x in group) / len(group) for cat in categories} for name, group in groups.items()}
        features[feature] = {"type": "CATEGORICAL", "groups": distributions, "top_minus_bottom_share": {cat: distributions["TOP_10_PCT"][cat] - distributions["BOTTOM_10_PCT"][cat] for cat in categories}}
    return {"group_counts": {name: len(group) for name, group in groups.items()}, "features": features}


def _numeric(values):
    values = sorted(float(x) for x in values if x is not None)
    if not values:
        return {"count": 0, "mean": None, "p25": None, "p50": None, "p75": None, "p90": None}
    return {"count": len(values), "mean": statistics.fmean(values), "p25": _quantile(values, .25), "p50": _quantile(values, .5), "p75": _quantile(values, .75), "p90": _quantile(values, .9)}


def _difference(summaries):
    if summaries["TOP_10_PCT"]["mean"] is None or summaries["BOTTOM_10_PCT"]["mean"] is None:
        return None
    return summaries["TOP_10_PCT"]["mean"] - summaries["BOTTOM_10_PCT"]["mean"]


def _quantile(values, q):
    if len(values) == 1: return values[0]
    position = (len(values) - 1) * q
    lower = math.floor(position); upper = math.ceil(position)
    return values[lower] if lower == upper else values[lower] + (values[upper] - values[lower]) * (position - lower)


def _histogram(values, edges):
    labels = [f"[{edges[i]},{edges[i+1]})" for i in range(len(edges) - 1)]
    counts = [0] * len(labels)
    for value in values:
        for index in range(len(edges) - 1):
            if edges[index] <= value < edges[index + 1]: counts[index] += 1; break
    return {"bins": labels, "counts": counts}
