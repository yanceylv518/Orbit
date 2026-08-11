"""Audit R-0 V2 liquidity-universe capacity without reading 15m signals or returns."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import json
from pathlib import Path
import statistics
from typing import Any


DAY_MS = 24 * 60 * 60 * 1000
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--minimum-volume", default="30000000")
    parser.add_argument("--training-end-ms", type=int, default=1_735_689_599_999)
    parser.add_argument("--lockbox-start-ms", type=int, default=1_735_689_600_000)
    parser.add_argument("--lockbox-end-ms", type=int, default=1_785_542_399_999)
    args = parser.parse_args()
    if args.lookback_days < 1:
        parser.error("lookback days must be positive")

    root = Path(args.root).resolve()
    contracts = json.loads(
        (root / "metadata" / "contracts.json").read_text(encoding="utf-8")
    )["contracts"]
    by_symbol = _load_liquidity(root, contracts, args.lockbox_end_ms)
    payload = {
        "protocol": "ORBIT_R0_V2_UNIVERSE_CAPACITY_AUDIT_V1",
        "inputs": {
            "liquidity_lookback_days": args.lookback_days,
            "minimum_median_daily_quote_volume_usdt": args.minimum_volume,
            "minimum_qualified_contracts_for_tiers": 3,
            "signal_or_return_data_read": False,
        },
        "training": _summarize_period(
            contracts,
            by_symbol,
            period_start_ms=0,
            period_end_ms=args.training_end_ms,
            lookback=args.lookback_days,
            minimum_volume=Decimal(args.minimum_volume),
        ),
        "lockbox": _summarize_period(
            contracts,
            by_symbol,
            period_start_ms=args.lockbox_start_ms,
            period_end_ms=args.lockbox_end_ms,
            lookback=args.lookback_days,
            minimum_volume=Decimal(args.minimum_volume),
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))


def _load_liquidity(
    root: Path,
    contracts: list[dict[str, Any]],
    maximum_time_ms: int,
) -> dict[str, dict[int, Decimal]]:
    result: dict[str, dict[int, Decimal]] = {}
    for contract in contracts:
        symbol = str(contract["symbol"])
        rows: dict[int, Decimal] = {}
        for path in sorted((root / "derived" / "daily_liquidity" / symbol).glob("*.jsonl.gz")):
            with gzip.open(path, "rt", encoding="utf-8") as source:
                for line in source:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    close_time = int(row["day_close_time_ms"])
                    if close_time > maximum_time_ms:
                        continue
                    if row.get("status") == "COMPLETE":
                        rows[close_time] = Decimal(str(row["quote_volume"]))
        result[symbol] = rows
    return result


def _summarize_period(
    contracts: list[dict[str, Any]],
    liquidity: dict[str, dict[int, Decimal]],
    *,
    period_start_ms: int,
    period_end_ms: int,
    lookback: int,
    minimum_volume: Decimal,
) -> dict[str, Any]:
    first_close = min(
        (close for rows in liquidity.values() for close in rows),
        default=period_end_ms,
    )
    first_day_open = max(period_start_ms // DAY_MS * DAY_MS, first_close // DAY_MS * DAY_MS)
    final_day_open = period_end_ms // DAY_MS * DAY_MS
    counts: list[int] = []
    symbols_seen: set[str] = set()
    eligible_days_by_year: dict[str, int] = defaultdict(int)
    snapshot_days_by_year: dict[str, int] = defaultdict(int)
    for day_open in range(first_day_open, final_day_open + 1, DAY_MS):
        required_closes = [day_open - offset * DAY_MS - 1 for offset in range(lookback)]
        qualified: list[str] = []
        for contract in contracts:
            listed_at = int(contract["listed_at_ms"])
            delisted_at = contract.get("delisted_at_ms")
            if day_open < listed_at or (delisted_at is not None and day_open >= int(delisted_at)):
                continue
            rows = liquidity.get(str(contract["symbol"]), {})
            values = [rows.get(close) for close in required_closes]
            if any(value is None for value in values):
                continue
            if Decimal(str(statistics.median(values))) >= minimum_volume:
                qualified.append(str(contract["symbol"]))
        count = len(qualified)
        counts.append(count)
        year = str(datetime.fromtimestamp(day_open / 1000, tz=timezone.utc).year)
        snapshot_days_by_year[year] += 1
        if count >= 3:
            eligible_days_by_year[year] += 1
            symbols_seen.update(qualified)
    ordered = sorted(counts)
    return {
        "snapshot_days": len(counts),
        "eligible_snapshot_days": sum(value >= 3 for value in counts),
        "qualified_contracts": {
            "minimum": ordered[0] if ordered else 0,
            "p25": _percentile(ordered, 0.25),
            "median": _percentile(ordered, 0.50),
            "p75": _percentile(ordered, 0.75),
            "maximum": ordered[-1] if ordered else 0,
        },
        "distinct_contracts_ever_eligible": len(symbols_seen),
        "snapshot_days_by_year": dict(sorted(snapshot_days_by_year.items())),
        "eligible_snapshot_days_by_year": dict(sorted(eligible_days_by_year.items())),
    }


def _percentile(values: list[int], probability: float) -> float:
    if not values:
        return 0.0
    position = probability * (len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return values[lower] * (1 - weight) + values[upper] * weight


if __name__ == "__main__":
    main()
