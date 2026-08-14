from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import statistics
from typing import Any, Mapping, Sequence

from orbit.application.rc0_funnel import signal_features
from orbit.domain.calibration.r0_shortline import (
    ShortlineCandle,
    breakout_direction,
    oversold_direction,
    simple_atr,
)


INTERVAL_MS = 900_000


def detect_sig1_signals(
    market_windows: Mapping[str, Mapping[str, Any]],
    signal_close_time_ms: int,
    spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Detect the frozen shapes on every completed 15-minute candle.

    RC-0B used a position-suppressed research event pool.  That pool is the
    frozen historical reference for workload and threshold calibration, not a
    hidden runtime gate.  SIG-1 deliberately evaluates every completed candle
    because every runtime signal receives its own (overlap-allowed) simulation.
    """
    market = spec["market"]
    minimum_liquidity = Decimal(str(market["liquidity"]["minimum_median_daily_quote_volume_usdt"]))
    required_days = int(market["liquidity"]["lookback_complete_utc_days"])
    eligible: list[tuple[str, Sequence[ShortlineCandle], Decimal]] = []
    for raw_symbol, window in market_windows.items():
        symbol = str(raw_symbol).upper()
        daily = [Decimal(str(value)) for value in window.get("daily_quote_volumes", [])]
        if len(daily) != required_days:
            continue
        liquidity = Decimal(str(statistics.median(daily)))
        if liquidity >= minimum_liquidity:
            eligible.append((symbol, list(window.get("candles", [])), liquidity))
    if len(eligible) < int(market["minimum_simultaneously_eligible_markets"]):
        return []

    results = []
    for symbol, candles, liquidity in eligible:
        indexes = {int(row.close_time_ms): index for index, row in enumerate(candles)}
        signal_index = indexes.get(int(signal_close_time_ms))
        if signal_index is None or signal_index < 96:
            continue
        if not _contiguous(candles[max(0, signal_index - 288) : signal_index + 1]):
            continue
        atr_period = int(spec["simulation"]["atr_period"])
        atr14 = simple_atr(candles, signal_index, atr_period)
        if atr14 <= 0:
            continue
        breakout = spec["signals"]["BREAKOUT_MOMENTUM"]
        breakout_side = breakout_direction(
            candles,
            signal_index,
            channel_lookback=int(breakout["channel_lookback_candles"]),
            volume_lookback=int(breakout["volume_lookback_candles"]),
            minimum_relative_volume=float(breakout["minimum_relative_quote_volume"]),
        )
        if breakout_side:
            results.append(
                _signal(
                    symbol,
                    candles,
                    signal_index,
                    atr14,
                    liquidity,
                    family_id="BREAKOUT_MOMENTUM",
                    direction="LONG" if breakout_side > 0 else "SHORT",
                    reason={
                        "channel_lookback_candles": int(breakout["channel_lookback_candles"]),
                        "relative_quote_volume": _relative_volume(
                            candles, signal_index, int(breakout["volume_lookback_candles"])
                        ),
                        "minimum_relative_quote_volume": float(
                            breakout["minimum_relative_quote_volume"]
                        ),
                    },
                )
            )
        oversold = spec["signals"]["OVERSOLD_REBOUND"]
        oversold_side = oversold_direction(
            candles,
            signal_index,
            return_lookback=int(oversold["return_lookback_candles"]),
            minimum_drop_fraction=float(oversold["minimum_drop_fraction"]),
        )
        if oversold_side:
            reference = float(candles[signal_index - int(oversold["return_lookback_candles"])].close)
            results.append(
                _signal(
                    symbol,
                    candles,
                    signal_index,
                    atr14,
                    liquidity,
                    family_id="OVERSOLD_REBOUND",
                    direction="LONG",
                    reason={
                        "return_lookback_candles": int(oversold["return_lookback_candles"]),
                        "drop_fraction": 1.0 - float(candles[signal_index].close) / reference,
                        "minimum_drop_fraction": float(oversold["minimum_drop_fraction"]),
                        "stabilized": True,
                    },
                )
            )
    return sorted(results, key=lambda row: (row["signal_time_ms"], row["symbol"], row["family_id"]))


def daily_workload_scope(signals: Sequence[Mapping[str, Any]], limit: int) -> dict[str, Any]:
    ranked = sorted(
        (dict(row) for row in signals),
        key=lambda row: (
            -float(row["trend_strength_96"]),
            int(row["signal_time_ms"]),
            str(row["symbol"]),
            str(row["signal_id"]),
        ),
    )
    included = ranked[: max(0, int(limit))]
    return {
        "total_signal_count": len(ranked),
        "included_signal_ids": [row["signal_id"] for row in included],
        "truncated_signal_ids": [row["signal_id"] for row in ranked[len(included) :]],
    }


def notification_message(signal: Mapping[str, Any]) -> dict[str, str]:
    direction = str(signal["direction"])
    entry = float(signal["reference_entry_price"])
    risk = float(signal["initial_risk_price"])
    sign = 1.0 if direction == "LONG" else -1.0
    reason = signal["reason"]
    if signal["family_id"] == "BREAKOUT_MOMENTUM":
        trigger = (
            f"32根突破 / 放量{float(reason['relative_quote_volume']):.2f}倍"
        )
    else:
        trigger = f"16根跌幅{float(reason['drop_fraction']):.1%}后企稳"
    body = "\n".join(
        [
            f"{signal['symbol']} {direction}",
            trigger,
            f"趋势强度 {float(signal['trend_strength_96']):.2f}（历史同族前10%门槛）",
            f"参考进场 {entry:.8g}  止损 {float(signal['suggested_stop_price']):.8g}",
            f"1R {entry + sign * risk:.8g} / 2R {entry + sign * 2 * risk:.8g} / 3R {entry + sign * 3 * risk:.8g}",
            f"信号时间 {iso_utc(int(signal['signal_time_ms']))}",
        ]
    )
    return {"title": f"Orbit 信号 · {signal['symbol']}", "message": body}


def signal_day(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def iso_utc(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _signal(symbol, candles, signal_index, atr14, liquidity, *, family_id, direction, reason):
    candle = candles[signal_index]
    features = signal_features(candles, signal_index, direction, atr14, 96)
    if features is None:
        raise RuntimeError("SIG-1 trend-strength history is unavailable")
    reference_entry = float(candle.close)
    risk = 2.0 * float(atr14)
    sign = 1.0 if direction == "LONG" else -1.0
    identity = {
        "protocol": "ORBIT_SIG1_SIGNAL_ID_V1",
        "family_id": family_id,
        "symbol": symbol,
        "signal_time_ms": int(candle.close_time_ms),
        "direction": direction,
    }
    signal_id = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return identity | {
        "signal_id": signal_id,
        "signal_day_utc": signal_day(int(candle.close_time_ms)),
        "signal_price": float(candle.close),
        "reference_entry_price": reference_entry,
        "atr14": float(atr14),
        "initial_risk_price": risk,
        "suggested_stop_price": reference_entry - sign * risk,
        "trend_strength_96": float(features["trend_strength"]),
        "median_daily_quote_volume_usdt": float(liquidity),
        "reason": reason,
        # Freeze the observable chart at decision time.  This is deliberately
        # limited to candles that had already closed when the signal fired.
        "chart_before": [
            {
                "open_time_ms": int(row.open_time_ms),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "quote_volume": float(row.quote_volume),
            }
            for row in candles[max(0, signal_index - 47) : signal_index + 1]
        ],
    }


def _relative_volume(candles, signal_index, lookback):
    baseline = statistics.median(
        float(row.quote_volume) for row in candles[signal_index - lookback : signal_index]
    )
    return float(candles[signal_index].quote_volume) / baseline


def _contiguous(candles: Sequence[ShortlineCandle]) -> bool:
    return all(
        int(right.open_time_ms) - int(left.open_time_ms) == INTERVAL_MS
        for left, right in zip(candles, candles[1:])
    )
