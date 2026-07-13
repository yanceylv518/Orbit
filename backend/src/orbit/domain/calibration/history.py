from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class MarketCandle:
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class FundingPoint:
    funding_time_ms: int
    funding_rate: float


def parse_candles(rows: Sequence[Any]) -> list[MarketCandle]:
    candles = []
    for row in rows:
        if isinstance(row, dict):
            candles.append(MarketCandle(
                int(row["close_time_ms"]), float(row["open"]), float(row["high"]),
                float(row["low"]), float(row["close"]),
            ))
        elif len(row) >= 5:
            candles.append(MarketCandle(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])))
        elif len(row) >= 2:
            close = float(row[1])
            candles.append(MarketCandle(int(row[0]), close, close, close, close))
        else:
            raise ValueError("unsupported candle row")
    return candles


def load_candles(path: str | Path) -> list[MarketCandle]:
    return parse_candles(json.loads(Path(path).read_text(encoding="utf-8")))


def parse_funding(rows: Sequence[Any]) -> list[FundingPoint]:
    points = []
    for row in rows:
        if isinstance(row, dict):
            time_ms = row.get("funding_time_ms", row.get("fundingTime"))
            rate = row.get("funding_rate", row.get("fundingRate"))
        else:
            time_ms, rate = row[0], row[1]
        points.append(FundingPoint(int(time_ms), float(rate)))
    return sorted(points, key=lambda point: point.funding_time_ms)


def load_funding(path: str | Path) -> list[FundingPoint]:
    return parse_funding(json.loads(Path(path).read_text(encoding="utf-8")))


def exclude_latest_candles(candles: Sequence[MarketCandle], count: int) -> list[MarketCandle]:
    if count < 0:
        raise ValueError("exclude count must not be negative")
    if count == 0:
        return list(candles)
    if count >= len(candles):
        raise ValueError("exclude count must leave at least one candle")
    return list(candles[:-count])
