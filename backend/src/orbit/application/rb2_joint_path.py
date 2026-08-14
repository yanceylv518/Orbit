from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Sequence

MFE_BUCKETS = ("LT_2R", "GTE_2_LT_5R", "GTE_5_LT_10R", "GTE_10R")
QUANTILES = (0.5, 0.75, 0.9, 0.95, 0.99)


def mfe_bucket(mfe_r: float) -> str:
    value = float(mfe_r)
    if value < 2:
        return "LT_2R"
    if value < 5:
        return "GTE_2_LT_5R"
    if value < 10:
        return "GTE_5_LT_10R"
    return "GTE_10R"


def quantile_distribution(values: Sequence[float]) -> dict[str, Any]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"event_count": 0}
    return {
        "event_count": len(ordered),
        "mean": statistics.fmean(ordered),
        "quantiles": {f"p{int(level * 100)}": _quantile(ordered, level) for level in QUANTILES},
    }


def joint_bucket_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    early_windows: Sequence[int] = (4, 8, 16, 32),
) -> dict[str, Any]:
    timing_counts = {"BEFORE_MFE": 0, "SAME_BAR": 0, "AFTER_MFE": 0, "NO_ADVERSE_EXCURSION": 0}
    for row in rows:
        mae_bar = int(row["mae_bar"])
        mfe_bar = int(row["mfe_bar"])
        if float(row["mae_r"]) == 0:
            relation = "NO_ADVERSE_EXCURSION"
        else:
            relation = "BEFORE_MFE" if mae_bar < mfe_bar else ("AFTER_MFE" if mae_bar > mfe_bar else "SAME_BAR")
        timing_counts[relation] += 1
    count = len(rows)
    return {
        "event_count": count,
        "mfe_r": quantile_distribution([float(row["mfe_r"]) for row in rows]),
        "mae_r": quantile_distribution([float(row["mae_r"]) for row in rows]),
        "mae_entry_price_pct": quantile_distribution([float(row["mae_entry_price_pct"]) for row in rows]),
        "mae_vs_mfe_timing": {
            "counts": timing_counts,
            "rates": {key: value / count if count else None for key, value in timing_counts.items()},
        },
        "early_mae": {
            str(window): {
                "mae_r": quantile_distribution([float(row[f"early_mae_{window}_r"]) for row in rows]),
                "mae_entry_price_pct": quantile_distribution(
                    [float(row[f"early_mae_{window}_entry_price_pct"]) for row in rows]
                ),
            }
            for window in early_windows
        },
    }


def _quantile(values: Sequence[float], level: float) -> float:
    position = (len(values) - 1) * level
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)
