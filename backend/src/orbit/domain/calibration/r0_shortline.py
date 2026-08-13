from __future__ import annotations

from collections import OrderedDict, defaultdict
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import itertools
import random
import statistics
from typing import Any, Callable, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint
from orbit.domain.calibration.shortline_dataset import (
    DAY_MS,
    RAW_INTERVAL_MS,
    ContractMetadata,
)


@dataclass(frozen=True)
class ShortlineCandle:
    open_time_ms: int
    close_time_ms: int
    open: float
    high: float
    low: float
    close: float
    quote_volume: float


@dataclass(frozen=True)
class UniverseMembership:
    tier: str
    median_daily_quote_volume: Decimal
    volume_trend_3d: str
    listing_age: str


def true_range(candle: ShortlineCandle, previous_close: float) -> float:
    return max(
        candle.high - candle.low,
        abs(candle.high - previous_close),
        abs(candle.low - previous_close),
    )


def simple_atr(candles: Sequence[ShortlineCandle], index: int, period: int = 14) -> float:
    if period < 1 or index < period or index >= len(candles):
        raise ValueError("ATR requires period candles plus the preceding close")
    ranges = [
        true_range(candles[item], candles[item - 1].close)
        for item in range(index - period + 1, index + 1)
    ]
    return sum(ranges) / period


def breakout_direction(
    candles: Sequence[ShortlineCandle],
    index: int,
    *,
    channel_lookback: int,
    volume_lookback: int,
    minimum_relative_volume: float,
) -> int:
    history = max(channel_lookback, volume_lookback)
    if index < history:
        return 0
    candle = candles[index]
    channel = candles[index - channel_lookback:index]
    volumes = [item.quote_volume for item in candles[index - volume_lookback:index]]
    baseline = statistics.median(volumes)
    if baseline <= 0 or candle.quote_volume / baseline < minimum_relative_volume:
        return 0
    if candle.close > max(item.high for item in channel):
        return 1
    if candle.close < min(item.low for item in channel):
        return -1
    return 0


def oversold_direction(
    candles: Sequence[ShortlineCandle],
    index: int,
    *,
    return_lookback: int,
    minimum_drop_fraction: float,
) -> int:
    if index < max(return_lookback, 1):
        return 0
    candle = candles[index]
    reference = candles[index - return_lookback].close
    oversold = candle.close / reference - 1 <= -minimum_drop_fraction
    stabilized = candle.close > candles[index - 1].close and candle.close >= candle.open
    return 1 if oversold and stabilized else 0


def frozen_parameter_grid(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    grids: list[dict[str, Any]] = []
    for family in contract["families"]:
        definition = family["definitions"][0]
        if definition["id"] == "B1_DONCHIAN_VOLUME":
            combinations = itertools.product(
                definition["channel_lookback_candles"],
                definition["minimum_relative_quote_volume"],
                definition["holding_candles"],
            )
            for channel, volume, holding in combinations:
                grids.append({
                    "family_id": family["id"],
                    "definition_id": definition["id"],
                    "parameters": {
                        "channel_lookback_candles": int(channel),
                        "minimum_relative_quote_volume": str(volume),
                        "holding_candles": int(holding),
                    },
                })
        elif definition["id"] == "S1_DROP_STABILIZATION":
            combinations = itertools.product(
                definition["return_lookback_candles"],
                definition["minimum_drop_fraction"],
                definition["holding_candles"],
            )
            for lookback, drop, holding in combinations:
                grids.append({
                    "family_id": family["id"],
                    "definition_id": definition["id"],
                    "parameters": {
                        "return_lookback_candles": int(lookback),
                        "minimum_drop_fraction": str(drop),
                        "holding_candles": int(holding),
                    },
                })
        else:
            raise ValueError(f"unsupported frozen definition: {definition['id']}")
    return grids


def simulate_symbol_events(
    symbol: str,
    candles: Sequence[ShortlineCandle],
    funding_points: Sequence[FundingPoint],
    definition_id: str,
    parameters: Mapping[str, Any],
    *,
    tier_at: Callable[[str, int], str | None],
    evaluation_start_ms: int,
    evaluation_end_ms: int,
    round_trip_cost_pct_by_tier: Mapping[str, float],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None = None,
    atr_period: int = 14,
    atr_multiple: float = 2.0,
    include_path_diagnostics: bool = False,
) -> list[dict[str, Any]]:
    ordered = list(candles)
    if any(
        left.open_time_ms > right.open_time_ms for left, right in zip(ordered, ordered[1:])
    ):
        ordered.sort(key=lambda item: item.open_time_ms)
    funding = list(funding_points)
    if any(
        left.funding_time_ms > right.funding_time_ms for left, right in zip(funding, funding[1:])
    ):
        funding.sort(key=lambda item: item.funding_time_ms)
    holding = int(parameters["holding_candles"])
    if holding < 1 or evaluation_end_ms < evaluation_start_ms:
        raise ValueError("invalid evaluation boundary or holding period")
    events: list[dict[str, Any]] = []
    funding_times = [item.funding_time_ms for item in funding]
    funding_prefix = [0.0]
    for item in funding:
        funding_prefix.append(funding_prefix[-1] + item.funding_rate)
    next_signal_index = 0
    for index, candle in enumerate(ordered):
        if index < next_signal_index or candle.close_time_ms < evaluation_start_ms:
            continue
        if definition_id == "B1_DONCHIAN_VOLUME":
            direction = breakout_direction(
                ordered, index,
                channel_lookback=int(parameters["channel_lookback_candles"]),
                volume_lookback=96,
                minimum_relative_volume=float(parameters["minimum_relative_quote_volume"]),
            )
            history = max(96, int(parameters["channel_lookback_candles"]), atr_period + 1)
        elif definition_id == "S1_DROP_STABILIZATION":
            direction = oversold_direction(
                ordered, index,
                return_lookback=int(parameters["return_lookback_candles"]),
                minimum_drop_fraction=float(parameters["minimum_drop_fraction"]),
            )
            history = max(int(parameters["return_lookback_candles"]), atr_period + 1)
        else:
            raise ValueError(f"unsupported definition: {definition_id}")
        if not direction:
            continue
        entry_index = index + 1
        time_exit_index = entry_index + holding
        if index < history or time_exit_index >= len(ordered):
            continue
        required = ordered[index - history:time_exit_index + 1]
        if not _is_contiguous(required):
            continue
        entry = ordered[entry_index]
        time_exit = ordered[time_exit_index]
        if entry.open_time_ms < evaluation_start_ms or time_exit.open_time_ms > evaluation_end_ms:
            continue
        tier = tier_at(symbol, candle.close_time_ms)
        if tier not in round_trip_cost_pct_by_tier:
            continue
        diagnostics = diagnostics_at(symbol, candle.close_time_ms) if diagnostics_at else None
        atr = simple_atr(ordered, index, atr_period)
        entry_price = entry.open
        stop_price = entry_price - direction * atr_multiple * atr
        exit_price = time_exit.open
        exit_time_ms = time_exit.open_time_ms
        exit_reason = "TIME"
        for held in ordered[entry_index:time_exit_index]:
            touched = held.low <= stop_price if direction > 0 else held.high >= stop_price
            if not touched:
                continue
            gap = held.open < stop_price if direction > 0 else held.open > stop_price
            exit_price = held.open if gap else stop_price
            exit_time_ms = held.open_time_ms
            exit_reason = "STOP_GAP" if gap else "STOP"
            break
        funding_start = bisect_right(funding_times, entry.open_time_ms)
        funding_end = bisect_right(funding_times, exit_time_ms)
        funding_rate = funding_prefix[funding_end] - funding_prefix[funding_start]
        price_return = direction * (exit_price / entry_price - 1)
        funding_return = -direction * funding_rate
        cost_pct = float(round_trip_cost_pct_by_tier[tier])
        net_return_pct = 100 * (price_return + funding_return) - cost_pct
        event = {
            "symbol": symbol,
            "definition_id": definition_id,
            "parameters": dict(parameters),
            "signal_time_ms": candle.close_time_ms,
            "entry_time_ms": entry.open_time_ms,
            "exit_time_ms": exit_time_ms,
            "entry_day_utc": _utc_day(entry.open_time_ms),
            "entry_year_utc": datetime.fromtimestamp(
                entry.open_time_ms / 1000, tz=timezone.utc,
            ).year,
            "direction": "LONG" if direction > 0 else "SHORT",
            "tier": tier,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "atr14": atr,
            "stop_price": stop_price,
            "exit_reason": exit_reason,
            "price_return_pct": price_return * 100,
            "funding_return_pct": funding_return * 100,
            "cost_pct": cost_pct,
            "net_return_pct": net_return_pct,
        }
        if include_path_diagnostics:
            event["path_diagnostics"] = measure_event_path(
                ordered,
                entry_index=entry_index,
                holding_candles=holding,
                direction=direction,
                entry_price=entry_price,
                atr=atr,
                stop_price=stop_price,
                exit_reason=exit_reason,
                exit_time_ms=exit_time_ms,
                evaluation_end_ms=evaluation_end_ms,
            )
        if diagnostics:
            event.update(diagnostics)
        events.append(event)
        next_signal_index = time_exit_index
    return events


def measure_event_path(
    candles: Sequence[ShortlineCandle],
    *,
    entry_index: int,
    holding_candles: int,
    direction: int,
    entry_price: float,
    atr: float,
    stop_price: float,
    exit_reason: str,
    exit_time_ms: int,
    evaluation_end_ms: int,
) -> dict[str, Any]:
    """Measure excursions without changing entry, exit, selection, or gates.

    Horizon measurements deliberately continue observing after an executed stop.
    The separate ``executed`` measurement is truncated at the actual exit. On a
    stop candle, OHLC cannot reveal whether its favorable extreme happened
    before or after the stop, so executed MFE uses only the candle open while
    the counterfactual H/2H horizons retain the full candle range.
    """
    if direction not in {-1, 1} or holding_candles < 1 or entry_price <= 0 or atr <= 0:
        raise ValueError("invalid R-0 path diagnostic input")

    def horizon(length: int) -> dict[str, Any] | None:
        end_index = entry_index + length
        if end_index > len(candles):
            return None
        observed = list(candles[entry_index:end_index])
        if not observed or observed[-1].close_time_ms > evaluation_end_ms or not _is_contiguous(observed):
            return None
        return _excursion_summary(observed, direction, entry_price, atr)

    h_path = horizon(holding_candles)
    double_h_path = horizon(holding_candles * 2)
    executed_rows = []
    stopped = exit_reason in {"STOP", "STOP_GAP"}
    for candle in candles[entry_index:entry_index + holding_candles]:
        if candle.open_time_ms > exit_time_ms:
            break
        if stopped and candle.open_time_ms == exit_time_ms:
            executed_rows.append(ShortlineCandle(
                candle.open_time_ms,
                candle.close_time_ms,
                candle.open,
                candle.open,
                candle.open,
                candle.open,
                candle.quote_volume,
            ))
            break
        executed_rows.append(candle)
    executed = _excursion_summary(executed_rows, direction, entry_price, atr)
    stop_bar = (
        next((
            index + 1 for index, candle in enumerate(
                candles[entry_index:entry_index + holding_candles]
            ) if candle.open_time_ms == exit_time_ms
        ), None)
        if stopped else None
    )

    return {
        "protocol": "ORBIT_R0_EVENT_PATH_DIAGNOSTIC_V1",
        "executed": executed,
        "holding_h": h_path,
        "holding_2h": double_h_path,
        "stop_bar": stop_bar,
        "stopped": stopped,
        "stop_then_new_mfe_h": _stop_preceded_new_mfe(stop_bar, executed, h_path),
        "stop_then_new_mfe_2h": _stop_preceded_new_mfe(stop_bar, executed, double_h_path),
        "stop_price_distance_atr": abs(entry_price - stop_price) / atr,
    }


def daily_block_bootstrap_interval(
    events: Sequence[Mapping[str, Any]],
    *,
    samples: int = 10_000,
    seed: int = 20_260_811,
) -> tuple[float, float]:
    if samples < 1:
        raise ValueError("bootstrap samples must be positive")
    blocks: dict[str, tuple[float, int]] = {}
    grouped: dict[str, list[float]] = defaultdict(list)
    for event in events:
        grouped[str(event["entry_day_utc"])].append(float(event["net_return_pct"]))
    for day, values in grouped.items():
        blocks[day] = (sum(values), len(values))
    if not blocks:
        return 0.0, 0.0
    ordered = [blocks[day] for day in sorted(blocks)]
    rng = random.Random(seed)
    size = len(ordered)
    means = []
    for _ in range(samples):
        selected = rng.choices(ordered, k=size)
        total = sum(item[0] for item in selected)
        count = sum(item[1] for item in selected)
        means.append(total / count)
    means.sort()
    return _percentile(means, 0.025), _percentile(means, 0.975)


def summarize_events(
    events: Sequence[Mapping[str, Any]],
    *,
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 20_260_811,
) -> dict[str, Any]:
    rows = list(events)
    overall = _group_summary(rows, bootstrap_samples, bootstrap_seed)
    result = {
        **overall,
        "by_tier": _dimension_summary(rows, "tier", bootstrap_samples, bootstrap_seed),
        "by_year": _dimension_summary(rows, "entry_year_utc", bootstrap_samples, bootstrap_seed),
        "by_symbol": _dimension_summary(rows, "symbol", bootstrap_samples, bootstrap_seed),
    }
    result["by_volume_trend_3d"] = _optional_dimension_summary(
        rows, "volume_trend_3d", bootstrap_samples, bootstrap_seed,
    )
    result["by_listing_age"] = _optional_dimension_summary(
        rows, "listing_age", bootstrap_samples, bootstrap_seed,
    )
    return result


def apply_gates(summary: Mapping[str, Any], gates: Mapping[str, Any]) -> dict[str, Any]:
    tier_rows = summary["by_tier"]
    year_rows = summary["by_year"]
    event_count = int(summary["event_count"])
    minimum_per_year = int(
        gates.get("minimum_events_per_calendar_year", gates.get("minimum_events_per_tier", 0))
    )
    qualifying_years = [
        key for key, item in year_rows.items() if int(item["event_count"]) >= minimum_per_year
    ]
    lockbox_years = {"2025", "2026"} if "minimum_events_per_calendar_year" in gates else set()
    minimum_years = int(gates.get("minimum_calendar_years_with_100_events", len(lockbox_years)))
    checks = {
        "minimum_events_total": event_count >= int(gates["minimum_events_total"]),
        "minimum_events_per_tier": all(
            int(tier_rows.get(tier, {}).get("event_count", 0))
            >= int(gates["minimum_events_per_tier"])
            for tier in ("HIGH", "MEDIUM", "LOW")
        ),
        "minimum_distinct_symbols": len(summary["by_symbol"])
        >= int(gates["minimum_distinct_symbols"]),
        "minimum_calendar_years": (
            lockbox_years.issubset(set(qualifying_years))
            if lockbox_years
            else len(qualifying_years) >= minimum_years
        ),
        "mean_net_return": float(summary["mean_net_return_pct"]) > 0,
        "bootstrap_lower_bound": float(summary["bootstrap_mean_ci_low"]) > 0,
        "minimum_positive_tier_means": sum(
            float(item["mean_net_return_pct"]) > 0 for item in tier_rows.values()
        ) >= int(gates["minimum_positive_tier_means"]),
        "leave_one_tier_out": all(
            _mean_without(summary, "tier", tier) > 0 for tier in ("HIGH", "MEDIUM", "LOW")
        ),
        "leave_one_year_out": bool(qualifying_years) and all(
            _mean_without(summary, "entry_year_utc", year) > 0 for year in qualifying_years
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def select_training_candidates(
    reports: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    result: dict[str, dict[str, Any] | None] = {}
    families = sorted({str(item["family_id"]) for item in reports})
    for family in families:
        passing = [
            item for item in reports
            if item["family_id"] == family and item["gate"]["passed"]
        ]
        passing.sort(key=lambda item: (
            -float(item["summary"]["bootstrap_mean_ci_low"]),
            -float(item["summary"]["mean_net_return_pct"]),
            -int(item["summary"]["event_count"]),
            str(item["definition_id"]),
            tuple((key, str(value)) for key, value in sorted(item["parameters"].items())),
        ))
        result[family] = passing[0] if passing else None
    return result


class HistoricalUniverseResolver:
    def __init__(
        self,
        contracts: Sequence[ContractMetadata | dict[str, Any]],
        liquidity_by_symbol: Mapping[str, Sequence[dict[str, Any]]],
        *,
        min_history_days: int,
        liquidity_lookback_days: int,
        minimum_volume: str,
        limit: int | None,
        tiers: Sequence[Mapping[str, Any]] | None = None,
        tiering: Mapping[str, Any] | None = None,
        cache_size: int = 4096,
    ):
        self.contracts = [
            item if isinstance(item, ContractMetadata) else ContractMetadata(**item)
            for item in contracts
        ]
        self.liquidity = {
            key: {int(row["day_close_time_ms"]): row for row in value}
            for key, value in liquidity_by_symbol.items()
        }
        self.min_history_days = min_history_days
        self.lookback = liquidity_lookback_days
        self.minimum_volume = minimum_volume
        self.minimum_volume_decimal = Decimal(minimum_volume)
        self.limit = limit
        self.tiers = list(tiers or [])
        self.tiering = dict(tiering or {})
        if self.tiering:
            expected = {
                "method": "DYNAMIC_EQUAL_THIRDS_BY_LIQUIDITY_RANK",
                "remainder_allocation": "HIGH_THEN_MEDIUM",
                "insufficient_qualified_contracts_policy": "EXCLUDE_ENTIRE_SNAPSHOT",
            }
            if any(self.tiering.get(key) != value for key, value in expected.items()):
                raise ValueError("unsupported dynamic tiering contract")
            if self.limit is not None or self.lookback != 3:
                raise ValueError("V2 dynamic tiers require no limit and a three-day window")
        self.cache_size = cache_size
        self._cache: OrderedDict[int, dict[str, UniverseMembership]] = OrderedDict()
        self._eligibility_boundary_days = {
            boundary // DAY_MS * DAY_MS
            for contract in self.contracts
            for boundary in (
                contract.listed_at_ms + self.min_history_days * DAY_MS,
                contract.listed_at_ms + 30 * DAY_MS,
                contract.delisted_at_ms,
            )
            if boundary is not None
        }

    def tier_at(self, symbol: str, timestamp_ms: int) -> str | None:
        membership = self.membership_at(symbol, timestamp_ms)
        return membership.tier if membership else None

    def diagnostics_at(self, symbol: str, timestamp_ms: int) -> dict[str, str] | None:
        membership = self.membership_at(symbol, timestamp_ms)
        if membership is None:
            return None
        return {
            "volume_trend_3d": membership.volume_trend_3d,
            "listing_age": membership.listing_age,
        }

    def membership_at(self, symbol: str, timestamp_ms: int) -> UniverseMembership | None:
        day_open = timestamp_ms // DAY_MS * DAY_MS
        cache_key = timestamp_ms if day_open in self._eligibility_boundary_days else day_open
        memberships = self._cache.get(cache_key)
        if memberships is None:
            eligibility_time = timestamp_ms if cache_key == timestamp_ms else day_open
            required_closes = [
                day_open - offset * DAY_MS - 1 for offset in range(self.lookback)
            ]
            scored: list[tuple[Decimal, str, list[Decimal], ContractMetadata]] = []
            for contract in self.contracts:
                if not contract.history_complete:
                    continue
                if eligibility_time < contract.listed_at_ms + self.min_history_days * DAY_MS:
                    continue
                if contract.delisted_at_ms is not None and eligibility_time >= contract.delisted_at_ms:
                    continue
                rows = self.liquidity.get(contract.symbol, {})
                window = [rows.get(close_time) for close_time in required_closes]
                if any(row is None or row.get("status") != "COMPLETE" for row in window):
                    continue
                chronological_values = [
                    Decimal(str(row["quote_volume"])) for row in reversed(window) if row
                ]
                values = sorted(chronological_values)
                middle = len(values) // 2
                score = (
                    values[middle]
                    if len(values) % 2
                    else (values[middle - 1] + values[middle]) / Decimal("2")
                )
                if score >= self.minimum_volume_decimal:
                    scored.append((score, contract.symbol, chronological_values, contract))
            scored.sort(key=lambda item: (-item[0], item[1]))
            ranked = scored if self.limit is None else scored[:self.limit]
            assigned_tiers = self._assign_tiers(len(ranked))
            memberships = {}
            for item, tier in zip(ranked, assigned_tiers):
                score, ranked_symbol, daily_values, contract = item
                memberships[ranked_symbol] = UniverseMembership(
                    tier=tier,
                    median_daily_quote_volume=score,
                    volume_trend_3d=(
                        "STRICTLY_INCREASING"
                        if len(daily_values) == 3
                        and daily_values[0] < daily_values[1] < daily_values[2]
                        else "NOT_STRICTLY_INCREASING"
                    ),
                    listing_age=(
                        "LE_30_DAYS"
                        if timestamp_ms - contract.listed_at_ms <= 30 * DAY_MS
                        else "GT_30_DAYS"
                    ),
                )
            self._cache[cache_key] = memberships
            if len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(cache_key)
        return memberships.get(symbol)

    def _assign_tiers(self, count: int) -> list[str]:
        if self.tiering:
            minimum = int(self.tiering["minimum_qualified_contracts"])
            if count < minimum:
                return []
            ordered = [str(item) for item in self.tiering["ordered_tiers"]]
            if ordered != ["HIGH", "MEDIUM", "LOW"]:
                raise ValueError("dynamic tier order must be HIGH, MEDIUM, LOW")
            base, remainder = divmod(count, 3)
            sizes = [base + (remainder >= 1), base + (remainder >= 2), base]
            return [tier for tier, size in zip(ordered, sizes) for _ in range(size)]
        assigned = []
        for rank in range(1, count + 1):
            tier_id = next((
                str(tier["id"]) for tier in self.tiers
                if int(tier["rank_start"]) <= rank <= int(tier["rank_end"])
            ), "")
            assigned.append(tier_id)
        return assigned


def _is_contiguous(candles: Sequence[ShortlineCandle]) -> bool:
    return all(
        right.open_time_ms - left.open_time_ms == RAW_INTERVAL_MS
        for left, right in zip(candles, candles[1:])
    )


def _excursion_summary(
    candles: Sequence[ShortlineCandle], direction: int, entry_price: float, atr: float,
) -> dict[str, Any]:
    if not candles:
        return {
            "mfe_pct": 0.0, "mae_pct": 0.0,
            "mfe_atr": 0.0, "mae_atr": 0.0,
            "mfe_bar": 0, "mae_bar": 0,
        }
    favorable = []
    adverse = []
    for candle in candles:
        if direction > 0:
            favorable.append(max(0.0, candle.high - entry_price))
            adverse.append(max(0.0, entry_price - candle.low))
        else:
            favorable.append(max(0.0, entry_price - candle.low))
            adverse.append(max(0.0, candle.high - entry_price))
    mfe = max(favorable)
    mae = max(adverse)
    return {
        "mfe_pct": mfe / entry_price * 100,
        "mae_pct": mae / entry_price * 100,
        "mfe_atr": mfe / atr,
        "mae_atr": mae / atr,
        "mfe_bar": favorable.index(mfe) + 1,
        "mae_bar": adverse.index(mae) + 1,
    }


def _stop_preceded_new_mfe(
    stop_bar: int | None,
    executed: Mapping[str, Any],
    horizon: Mapping[str, Any] | None,
) -> bool | None:
    if stop_bar is None or horizon is None:
        return False if stop_bar is None else None
    return (
        int(horizon["mfe_bar"]) > stop_bar
        and float(horizon["mfe_pct"]) > float(executed["mfe_pct"]) + 1e-12
    )


def _utc_day(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()


def _group_summary(rows: Sequence[Mapping[str, Any]], samples: int, seed: int) -> dict[str, Any]:
    values = [float(item["net_return_pct"]) for item in rows]
    low, high = daily_block_bootstrap_interval(rows, samples=samples, seed=seed)
    return {
        "event_count": len(rows),
        "mean_net_return_pct": sum(values) / len(values) if values else 0.0,
        "bootstrap_mean_ci_low": low,
        "bootstrap_mean_ci_high": high,
        "event_net_return_sum_pct": sum(values),
    }


def _dimension_summary(
    rows: Sequence[Mapping[str, Any]], key: str, samples: int, seed: int,
) -> dict[str, Any]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {
        name: _group_summary(values, samples, seed)
        for name, values in sorted(groups.items())
    }


def _optional_dimension_summary(
    rows: Sequence[Mapping[str, Any]], key: str, samples: int, seed: int,
) -> dict[str, Any]:
    present = [row for row in rows if key in row]
    if len(present) != len(rows):
        return {}
    return _dimension_summary(present, key, samples, seed)


def _mean_without(summary: Mapping[str, Any], dimension: str, excluded: Any) -> float:
    groups = summary["by_tier"] if dimension == "tier" else summary["by_year"]
    remaining = [
        item for key, item in groups.items() if str(key) != str(excluded)
    ]
    count = sum(int(item["event_count"]) for item in remaining)
    total = sum(float(item["event_net_return_sum_pct"]) for item in remaining)
    return total / count if count else float("-inf")


def _percentile(values: Sequence[float], quantile: float) -> float:
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight
