from __future__ import annotations

from bisect import bisect_right
from collections import deque
import math
import statistics
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.r0_shortline import ShortlineCandle

HORIZONS = (96, 288, 960)
QUANTILES = (.5, .75, .9, .95, .99)


def aggregate_completed_4h(candles: Sequence[ShortlineCandle]) -> list[tuple[int, float]]:
    buckets: dict[int, list[ShortlineCandle]] = {}
    span = 4 * 60 * 60 * 1000
    for row in candles:
        buckets.setdefault(row.open_time_ms // span * span, []).append(row)
    result = []
    for start, rows in sorted(buckets.items()):
        ordered = sorted(rows, key=lambda x: x.open_time_ms)
        if len(ordered) == 16 and ordered[0].open_time_ms == start and ordered[-1].close_time_ms == start + span - 1:
            result.append((ordered[-1].close_time_ms, ordered[-1].close))
    return result


def trend_series(bars: Sequence[tuple[int, float]]) -> list[dict[str, Any]]:
    result, prior, duration = [], None, 0
    closes = [float(x[1]) for x in bars]
    for index, (close_time, close) in enumerate(bars):
        if index < 360:
            result.append({"close_time_ms": close_time, "state": None})
            continue
        ma50 = statistics.fmean(closes[index - 49:index + 1])
        ret20 = close / closes[index - 120] - 1
        ret60 = close / closes[index - 360] - 1
        state = "UP" if close > ma50 and ret20 > 0 and ret60 > 0 else ("DOWN" if close < ma50 and ret20 < 0 and ret60 < 0 else "RANGE")
        duration = duration + 1 if state == prior else 1
        prior = state
        result.append({"close_time_ms": close_time, "state": state, "ma50_deviation_pct": (close / ma50 - 1) * 100, "return_20d_pct": ret20 * 100, "return_60d_pct": ret60 * 100, "duration_4h_bars": duration})
    return result


def trend_at(series: Sequence[Mapping[str, Any]], signal_close_ms: int) -> Mapping[str, Any] | None:
    times = [int(x["close_time_ms"]) for x in series]
    index = bisect_right(times, signal_close_ms) - 1
    if index < 0 or series[index].get("state") is None:
        return None
    return series[index]


def future_extrema(candles: Sequence[ShortlineCandle], horizon: int) -> tuple[list[int], list[int]]:
    """Return future max-high/min-low indexes for windows [i, i+horizon)."""
    size = len(candles); maxima = [-1] * size; minima = [-1] * size
    high_q: deque[int] = deque(); low_q: deque[int] = deque()
    for index in range(size - 1, -1, -1):
        limit = index + horizon
        while high_q and high_q[0] >= limit: high_q.popleft()
        while low_q and low_q[0] >= limit: low_q.popleft()
        while high_q and candles[high_q[-1]].high <= candles[index].high: high_q.pop()
        while low_q and candles[low_q[-1]].low >= candles[index].low: low_q.pop()
        high_q.append(index); low_q.append(index)
        if index + horizon <= size:
            maxima[index] = high_q[0]; minima[index] = low_q[0]
    return maxima, minima


def path_metrics(candles, entry_index, direction, entry_price, initial_r, horizon, extrema):
    if entry_index + horizon > len(candles) or initial_r <= 0:
        return None
    high_index, low_index = extrema[0][entry_index], extrema[1][entry_index]
    if direction == "LONG":
        favorable = max(0.0, candles[high_index].high - entry_price)
        adverse = max(0.0, entry_price - candles[low_index].low)
        mfe_index = high_index
        mae_index = low_index
    else:
        favorable = max(0.0, entry_price - candles[low_index].low)
        adverse = max(0.0, candles[high_index].high - entry_price)
        mfe_index = low_index
        mae_index = high_index
    mfe_r, mae_r = favorable / initial_r, adverse / initial_r
    return {
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "smoothness": mfe_r / max(mae_r, 1e-6),
        "mfe_bar": mfe_index - entry_index + 1,
        "mae_bar": mae_index - entry_index + 1,
    }


def horizon_summary(rows: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    mfe = sorted(float(x["mfe_r"]) for x in rows); mae = sorted(float(x["mae_r"]) for x in rows)
    bars = sorted(float(x["mfe_bar"]) for x in rows)
    def qs(values): return {f"p{int(q*100)}": _q(values, q) for q in QUANTILES}
    positive = sum(mfe)
    ordered = sorted(mfe, reverse=True)
    tails = {f"top_{p}_pct": sum(ordered[:max(1, math.ceil(len(ordered)*p/100))]) / positive if positive else None for p in (1,5,10,20)}
    return {"event_count": len(rows), "mfe_r_quantiles": qs(mfe), "mae_r_quantiles": qs(mae), "touch_rate": {f"gte_{level}r": sum(x >= level for x in mfe)/len(mfe) for level in (2,3,5,10)}, "mfe_tail_contribution": tails, "time_to_mfe_bars_quantiles": qs(bars)}


def _q(values, q):
    position = (len(values)-1)*q; lo, hi = math.floor(position), math.ceil(position)
    return values[lo] if lo == hi else values[lo] + (values[hi]-values[lo])*(position-lo)
