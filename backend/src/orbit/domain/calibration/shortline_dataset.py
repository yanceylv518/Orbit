from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence


RAW_INTERVAL = "15m"
RAW_INTERVAL_MS = 15 * 60 * 1000
TARGET_INTERVALS_MS = {"1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000}
DAY_MS = 24 * 60 * 60 * 1000


class DatasetInvariantError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveCandle:
    open_time_ms: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    close_time_ms: int
    quote_volume: str
    trade_count: int
    taker_buy_base_volume: str
    taker_buy_quote_volume: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AggregatedCandle:
    open_time_ms: int
    close_time_ms: int
    interval: str
    status: str
    observed_children: int
    expected_children: int
    missing_open_times_ms: tuple[int, ...]
    open: str | None = None
    high: str | None = None
    low: str | None = None
    close: str | None = None
    volume: str | None = None
    quote_volume: str | None = None
    trade_count: int | None = None
    taker_buy_base_volume: str | None = None
    taker_buy_quote_volume: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_open_times_ms"] = list(self.missing_open_times_ms)
        return payload


@dataclass(frozen=True)
class ContractMetadata:
    symbol: str
    listed_at_ms: int
    first_open_time_ms: int
    last_close_time_ms: int
    delisted_at_ms: int | None
    status: str
    status_method: str
    history_complete: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_archive_candle(row: Sequence[Any]) -> ArchiveCandle:
    if len(row) < 11:
        raise DatasetInvariantError("Binance kline row must contain at least 11 columns")
    try:
        candle = ArchiveCandle(
            open_time_ms=int(row[0]),
            open=_decimal_text(row[1]),
            high=_decimal_text(row[2]),
            low=_decimal_text(row[3]),
            close=_decimal_text(row[4]),
            volume=_decimal_text(row[5]),
            close_time_ms=int(row[6]),
            quote_volume=_decimal_text(row[7]),
            trade_count=int(row[8]),
            taker_buy_base_volume=_decimal_text(row[9]),
            taker_buy_quote_volume=_decimal_text(row[10]),
        )
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise DatasetInvariantError("invalid Binance kline row") from exc
    if candle.open_time_ms < 0 or candle.close_time_ms != candle.open_time_ms + RAW_INTERVAL_MS - 1:
        raise DatasetInvariantError("15m candle timestamps are not aligned")
    prices = tuple(Decimal(value) for value in (candle.open, candle.high, candle.low, candle.close))
    if min(prices) <= 0 or Decimal(candle.low) > min(Decimal(candle.open), Decimal(candle.close)):
        raise DatasetInvariantError("invalid candle price range")
    if Decimal(candle.high) < max(Decimal(candle.open), Decimal(candle.close)):
        raise DatasetInvariantError("invalid candle price range")
    if min(Decimal(candle.volume), Decimal(candle.quote_volume)) < 0 or candle.trade_count < 0:
        raise DatasetInvariantError("candle volume and trade count must not be negative")
    return candle


def validate_candle_sequence(candles: Sequence[ArchiveCandle]) -> dict[str, Any]:
    ordered = sorted(candles, key=lambda item: item.open_time_ms)
    duplicates: list[int] = []
    duplicate_count = 0
    missing: list[int] = []
    missing_ranges: list[dict[str, int]] = []
    missing_range_count = 0
    missing_count = 0
    previous: int | None = None
    for candle in ordered:
        if previous is not None:
            if candle.open_time_ms == previous:
                duplicate_count += 1
                if len(duplicates) < 1000:
                    duplicates.append(candle.open_time_ms)
            elif candle.open_time_ms > previous + RAW_INTERVAL_MS:
                start = previous + RAW_INTERVAL_MS
                count = (candle.open_time_ms - start) // RAW_INTERVAL_MS
                missing_count += count
                missing_range_count += 1
                if len(missing_ranges) < 1000:
                    missing_ranges.append({
                        "start_open_time_ms": start,
                        "end_open_time_ms": candle.open_time_ms - RAW_INTERVAL_MS,
                        "count": count,
                    })
                remaining = max(0, 1000 - len(missing))
                missing.extend(
                    start + index * RAW_INTERVAL_MS for index in range(min(count, remaining))
                )
        previous = candle.open_time_ms
    return {
        "rows": len(ordered),
        "duplicate_open_times_ms": duplicates,
        "duplicate_count": duplicate_count,
        "duplicate_samples_truncated": duplicate_count > len(duplicates),
        "missing_open_times_ms": missing,
        "missing_ranges": missing_ranges,
        "missing_range_count": missing_range_count,
        "missing_ranges_truncated": missing_range_count > len(missing_ranges),
        "missing_count": missing_count,
        "missing_samples_truncated": missing_count > len(missing),
        "complete": duplicate_count == 0 and missing_count == 0,
    }


def aggregate_candles(
    candles: Sequence[ArchiveCandle],
    interval: str,
) -> list[AggregatedCandle]:
    target_ms = TARGET_INTERVALS_MS.get(interval)
    if target_ms is None:
        raise DatasetInvariantError(f"unsupported aggregate interval: {interval}")
    expected_count = target_ms // RAW_INTERVAL_MS
    groups: dict[int, list[ArchiveCandle]] = {}
    for candle in sorted(candles, key=lambda item: item.open_time_ms):
        bucket = candle.open_time_ms // target_ms * target_ms
        groups.setdefault(bucket, []).append(candle)
    if not groups:
        return []

    result: list[AggregatedCandle] = []
    first_bucket = min(groups)
    last_bucket = max(groups)
    for bucket in range(first_bucket, last_bucket + target_ms, target_ms):
        children = groups.get(bucket, [])
        by_open = {item.open_time_ms: item for item in children}
        expected = tuple(bucket + index * RAW_INTERVAL_MS for index in range(expected_count))
        missing = tuple(timestamp for timestamp in expected if timestamp not in by_open)
        duplicate_count = len(children) - len(by_open)
        if missing or duplicate_count:
            result.append(AggregatedCandle(
                open_time_ms=bucket,
                close_time_ms=bucket + target_ms - 1,
                interval=interval,
                status="INCOMPLETE",
                observed_children=len(by_open),
                expected_children=expected_count,
                missing_open_times_ms=missing,
            ))
            continue
        ordered = [by_open[timestamp] for timestamp in expected]
        result.append(AggregatedCandle(
            open_time_ms=bucket,
            close_time_ms=bucket + target_ms - 1,
            interval=interval,
            status="COMPLETE",
            observed_children=expected_count,
            expected_children=expected_count,
            missing_open_times_ms=(),
            open=ordered[0].open,
            high=_decimal_text(max(Decimal(item.high) for item in ordered)),
            low=_decimal_text(min(Decimal(item.low) for item in ordered)),
            close=ordered[-1].close,
            volume=_sum_text(item.volume for item in ordered),
            quote_volume=_sum_text(item.quote_volume for item in ordered),
            trade_count=sum(item.trade_count for item in ordered),
            taker_buy_base_volume=_sum_text(item.taker_buy_base_volume for item in ordered),
            taker_buy_quote_volume=_sum_text(item.taker_buy_quote_volume for item in ordered),
        ))
    return result


def daily_liquidity(candles: Sequence[ArchiveCandle]) -> list[dict[str, Any]]:
    groups: dict[int, list[ArchiveCandle]] = {}
    for candle in candles:
        day_open = candle.open_time_ms // DAY_MS * DAY_MS
        groups.setdefault(day_open, []).append(candle)
    rows = []
    for day_open, children in sorted(groups.items()):
        sequence = validate_candle_sequence(children)
        complete = (
            len(children) == DAY_MS // RAW_INTERVAL_MS
            and min(item.open_time_ms for item in children) == day_open
            and max(item.open_time_ms for item in children) == day_open + DAY_MS - RAW_INTERVAL_MS
            and sequence["complete"]
        )
        rows.append({
            "day_open_time_ms": day_open,
            "day_close_time_ms": day_open + DAY_MS - 1,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "observed_candles": len({item.open_time_ms for item in children}),
            "expected_candles": DAY_MS // RAW_INTERVAL_MS,
            "quote_volume": _sum_text(item.quote_volume for item in children) if complete else None,
            "trade_count": sum(item.trade_count for item in children) if complete else None,
        })
    return rows


def infer_contract_metadata(
    symbol: str,
    candles: Sequence[ArchiveCandle],
    *,
    dataset_cutoff_ms: int,
    active_symbols: set[str] | None = None,
    stale_after_days: int = 45,
    history_complete: bool = True,
) -> ContractMetadata:
    if not candles:
        raise DatasetInvariantError(f"cannot infer metadata for empty contract: {symbol}")
    ordered = sorted(candles, key=lambda item: item.open_time_ms)
    normalized = symbol.upper().strip()
    if active_symbols is not None:
        active = normalized in {item.upper() for item in active_symbols}
        method = "EXCHANGE_INFO_SNAPSHOT"
    else:
        active = ordered[-1].close_time_ms >= dataset_cutoff_ms - stale_after_days * DAY_MS
        method = "ARCHIVE_STALENESS_HEURISTIC"
    return ContractMetadata(
        symbol=normalized,
        listed_at_ms=ordered[0].open_time_ms,
        first_open_time_ms=ordered[0].open_time_ms,
        last_close_time_ms=ordered[-1].close_time_ms,
        delisted_at_ms=None if active else ordered[-1].close_time_ms + 1,
        status="TRADING" if active else "DELISTED",
        status_method=method,
        history_complete=history_complete,
    )


def universe_at(
    timestamp_ms: int,
    contracts: Sequence[ContractMetadata | dict[str, Any]],
    *,
    min_history_days: int,
    liquidity_by_symbol: dict[str, Sequence[dict[str, Any]]] | None = None,
    liquidity_lookback_days: int = 7,
    min_median_quote_volume: Decimal | str | int | float = Decimal("0"),
    limit: int | None = None,
) -> list[str]:
    if timestamp_ms < 0 or min_history_days < 0 or liquidity_lookback_days <= 0:
        raise DatasetInvariantError("invalid universe query parameters")
    threshold = Decimal(str(min_median_quote_volume))
    ranked: list[tuple[Decimal, str]] = []
    for item in contracts:
        contract = item if isinstance(item, ContractMetadata) else ContractMetadata(**item)
        if not contract.history_complete:
            continue
        if timestamp_ms < contract.listed_at_ms + min_history_days * DAY_MS:
            continue
        if contract.delisted_at_ms is not None and timestamp_ms >= contract.delisted_at_ms:
            continue
        score = Decimal("0")
        if liquidity_by_symbol is not None:
            visible = [
                row for row in liquidity_by_symbol.get(contract.symbol, ())
                if row.get("status") == "COMPLETE"
                and int(row["day_close_time_ms"]) < timestamp_ms
            ][-liquidity_lookback_days:]
            if len(visible) < liquidity_lookback_days:
                continue
            values = sorted(Decimal(str(row["quote_volume"])) for row in visible)
            middle = len(values) // 2
            score = (
                values[middle]
                if len(values) % 2
                else (values[middle - 1] + values[middle]) / Decimal("2")
            )
            if score < threshold:
                continue
        ranked.append((score, contract.symbol))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if limit is not None:
        if limit <= 0:
            raise DatasetInvariantError("universe limit must be positive")
        ranked = ranked[:limit]
    return [symbol for _, symbol in ranked]


def compare_native_aggregate(
    derived: Sequence[AggregatedCandle],
    native_rows: Iterable[Sequence[Any]],
) -> dict[str, Any]:
    native = {}
    for row in native_rows:
        if len(row) < 11:
            raise DatasetInvariantError("native aggregate row must contain at least 11 columns")
        native[int(row[0])] = {
            "open": _decimal_text(row[1]), "high": _decimal_text(row[2]),
            "low": _decimal_text(row[3]), "close": _decimal_text(row[4]),
            "volume": _decimal_text(row[5]), "quote_volume": _decimal_text(row[7]),
            "trade_count": int(row[8]),
            "taker_buy_base_volume": _decimal_text(row[9]),
            "taker_buy_quote_volume": _decimal_text(row[10]),
        }
    compared = 0
    mismatches = []
    derived_open_times = {
        candle.open_time_ms for candle in derived if candle.status == "COMPLETE"
    }
    incomplete_open_times = {
        candle.open_time_ms for candle in derived if candle.status == "INCOMPLETE"
    }
    all_derived_open_times = derived_open_times | incomplete_open_times
    for candle in derived:
        if candle.status != "COMPLETE" or candle.open_time_ms not in native:
            continue
        compared += 1
        actual = {key: getattr(candle, key) for key in native[candle.open_time_ms]}
        if actual != native[candle.open_time_ms]:
            mismatches.append({
                "open_time_ms": candle.open_time_ms,
                "derived": actual,
                "native": native[candle.open_time_ms],
            })
    missing_in_native = sorted(derived_open_times - set(native))
    missing_in_derived = sorted(set(native) - all_derived_open_times)
    native_for_incomplete_derived = sorted(set(native) & incomplete_open_times)
    return {
        "compared": compared,
        "mismatches": mismatches,
        "missing_in_native": missing_in_native,
        "missing_in_derived": missing_in_derived,
        "native_for_incomplete_derived": native_for_incomplete_derived,
        "passed": (
            compared > 0 and not mismatches
            and not missing_in_native and not missing_in_derived
        ),
    }


def utc_iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _decimal_text(value: Any) -> str:
    number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    if not number.is_finite():
        raise DatasetInvariantError("numeric values must be finite")
    text = format(number, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _sum_text(values: Iterable[str]) -> str:
    return _decimal_text(sum((Decimal(value) for value in values), Decimal("0")))
