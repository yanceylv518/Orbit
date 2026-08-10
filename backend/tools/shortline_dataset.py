"""Build the survivorship-safe DATA-1R research dataset from Binance public archives.

The default dataset root is isolated from TB4 and existing calibration caches:
``var/calibration/shortline-data-v1``. Network commands never require credentials.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.shortline_dataset import (  # noqa: E402
    DATASET_PROTOCOL,
    ShortlineDatasetBuilder,
    ShortlineDatasetError,
    filter_archive_objects,
    load_archive_index,
    load_jsonl_gzip,
    write_archive_index,
)
from orbit.domain.calibration.shortline_dataset import (  # noqa: E402
    AggregatedCandle,
    compare_native_aggregate,
    universe_at,
)
from orbit.infrastructure.market_data.binance_public_archive import (  # noqa: E402
    ArchiveDownloader,
    ArchiveError,
    ArchiveObject,
    BinancePublicArchiveIndex,
    iter_csv_zip_rows,
)


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DEFAULT_ROOT = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="Enumerate all historical USD-M archive objects")
    index.add_argument("--no-funding", action="store_true")
    index.add_argument("--symbol", action="append", default=[])

    sync = commands.add_parser("sync", help="Download checksum-verified raw partitions")
    sync.add_argument("--symbol", action="append", default=[])
    sync.add_argument("--start-month")
    sync.add_argument("--end-month")
    sync.add_argument("--kind", action="append", choices=["KLINE_15M", "FUNDING"])
    sync.add_argument("--workers", type=int, default=4)
    sync.add_argument("--max-files", type=int)
    sync.add_argument("--confirm-full-download", action="store_true")

    build = commands.add_parser("build", help="Build 1h/4h, liquidity, metadata and manifest")
    build.add_argument("--active-symbols-file")
    build.add_argument("--dataset-cutoff")
    build.add_argument("--allow-partial", action="store_true")

    verify = commands.add_parser("verify-native", help="Compare local aggregates with native archive")
    verify.add_argument("--symbol", required=True)
    verify.add_argument("--month", required=True)
    verify.add_argument("--interval", required=True, choices=["1h", "4h"])

    query = commands.add_parser("universe", help="Query the point-in-time liquidity universe")
    query.add_argument("--timestamp", required=True)
    query.add_argument("--min-history-days", type=int, default=30)
    query.add_argument("--lookback-days", type=int, default=7)
    query.add_argument("--min-median-quote-volume", default="0")
    query.add_argument("--limit", type=int)

    args = parser.parse_args()
    root = validated_dataset_root(Path(args.root))
    if args.command == "index":
        payload = build_archive_index(
            root, requested_symbols=set(args.symbol) or None,
            include_funding=not args.no_funding,
        )
        objects = load_archive_index(root / "metadata" / "archive_index.json")
        print(json.dumps({
            "objects": len(objects), "symbols": len({item.symbol for item in objects}),
            "objects_sha256": payload["objects_sha256"],
        }, ensure_ascii=False))
    elif args.command == "sync":
        _validate_month(args.start_month)
        _validate_month(args.end_month)
        objects = filter_archive_objects(
            load_archive_index(root / "metadata" / "archive_index.json"),
            symbols=set(args.symbol) or None,
            start_month=args.start_month,
            end_month=args.end_month,
            kinds=set(args.kind) if args.kind else None,
        )
        if args.max_files is not None:
            if args.max_files <= 0:
                raise SystemExit("--max-files must be positive")
            objects = objects[:args.max_files]
        unrestricted = not args.symbol and not args.start_month and not args.end_month and not args.max_files
        if unrestricted and not args.confirm_full_download:
            raise SystemExit("full archive sync requires --confirm-full-download")
        sync_state_path = root / "metadata" / "sync_state.json"
        sync_progress = {"count": 0, "recent": []}
        _write_state(sync_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "RUNNING",
            "selected_files": len(objects), "completed_count": 0, "recent_files": [],
        })
        try:
            results = ShortlineDatasetBuilder(root).sync(
                objects, workers=args.workers,
                on_result=lambda item: _record_sync_progress(
                    sync_state_path, len(objects), sync_progress, item,
                ),
            )
        except BaseException as exc:
            _write_state(sync_state_path, {
                "protocol": DATASET_PROTOCOL,
                "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                "selected_files": len(objects),
                "completed_count": sync_progress["count"],
                "recent_files": sync_progress["recent"],
                "error": type(exc).__name__,
            })
            raise
        _write_state(sync_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
            "selected_files": len(objects),
            "completed_count": sync_progress["count"],
            "recent_files": sync_progress["recent"],
        })
        print(json.dumps({
            "files": len(results),
            "downloaded": sum(item["status"] == "DOWNLOADED" for item in results),
            "unchanged": sum(item["status"] == "UNCHANGED" for item in results),
        }, ensure_ascii=False))
    elif args.command == "build":
        active = load_active_symbols(Path(args.active_symbols_file)) if args.active_symbols_file else None
        cutoff = parse_timestamp(args.dataset_cutoff) if args.dataset_cutoff else None
        build_state_path = root / "metadata" / "build_state.json"
        _write_state(build_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "RUNNING",
            "allow_partial": bool(args.allow_partial),
        })
        try:
            result = ShortlineDatasetBuilder(root).build(
                active_symbols=active, dataset_cutoff_ms=cutoff,
                allow_partial=args.allow_partial,
            )
        except BaseException as exc:
            _write_state(build_state_path, {
                "protocol": DATASET_PROTOCOL,
                "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                "allow_partial": bool(args.allow_partial), "error": type(exc).__name__,
            })
            raise
        _write_state(build_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
            "allow_partial": bool(args.allow_partial),
            "dataset_state": result["quality_report"]["dataset_state"],
            "dataset_fingerprint": result["manifest"]["dataset_fingerprint"],
        })
        print(json.dumps({
            "contracts": len(result["contracts"]),
            "dataset_fingerprint": result["manifest"]["dataset_fingerprint"],
            "quality_report_sha256": result["quality_report"]["report_sha256"],
            "dataset_state": result["quality_report"]["dataset_state"],
        }, ensure_ascii=False))
    elif args.command == "verify-native":
        _validate_month(args.month)
        result = verify_native(root, args.symbol.upper(), args.month, args.interval)
        print(json.dumps(result, ensure_ascii=False))
        if not result["passed"]:
            raise SystemExit(2)
    elif args.command == "universe":
        result = query_universe(
            root, parse_timestamp(args.timestamp), args.min_history_days,
            args.lookback_days, args.min_median_quote_volume, args.limit,
        )
        print(json.dumps({"timestamp_ms": parse_timestamp(args.timestamp), "symbols": result}))


def validated_dataset_root(path: Path) -> Path:
    root = path.resolve()
    calibration = (PROJECT_ROOT / "var" / "calibration").resolve()
    if root == calibration or root == PROJECT_ROOT.resolve() or calibration not in root.parents:
        raise SystemExit("dataset root must be a dedicated child of var/calibration")
    manifest = root / "manifest.json"
    if manifest.exists():
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("protocol") != DATASET_PROTOCOL:
            raise SystemExit("dataset root contains a different manifest protocol")
    return root


def build_archive_index(
    root: Path,
    *,
    requested_symbols: set[str] | None,
    include_funding: bool,
) -> dict:
    client = BinancePublicArchiveIndex()
    symbols = (
        sorted({item.upper() for item in requested_symbols})
        if requested_symbols else client.discover_symbols()
    )
    index_path = root / "metadata" / "archive_index.json"
    existing = load_archive_index(index_path) if index_path.exists() else []
    existing_payload = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    scope = (
        "ALL_USDT_PERPETUAL"
        if requested_symbols is None or existing_payload.get("scope") == "ALL_USDT_PERPETUAL"
        else "SELECTED_SYMBOLS"
    )
    by_key = {item.key: item for item in existing}
    state_path = root / "metadata" / "archive_index_state.json"
    completed = []
    try:
        for position, symbol in enumerate(symbols, start=1):
            _write_state(state_path, {
                "protocol": DATASET_PROTOCOL, "status": "RUNNING",
                "total_symbols": len(symbols), "completed_symbols": completed,
                "current_symbol": symbol,
            })
            for item in client.discover_symbol(symbol, include_funding=include_funding):
                by_key[item.key] = item
            completed.append(symbol)
            if position % 10 == 0 or position == len(symbols):
                write_archive_index(index_path, list(by_key.values()), scope=scope)
        payload = write_archive_index(index_path, list(by_key.values()), scope=scope)
        _write_state(state_path, {
            "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
            "total_symbols": len(symbols), "completed_symbols": completed,
            "current_symbol": None, "objects_sha256": payload["objects_sha256"],
        })
        return payload
    except BaseException as exc:
        if by_key:
            write_archive_index(index_path, list(by_key.values()), scope=scope)
        _write_state(state_path, {
            "protocol": DATASET_PROTOCOL,
            "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
            "total_symbols": len(symbols), "completed_symbols": completed,
            "current_symbol": symbols[len(completed)] if len(completed) < len(symbols) else None,
            "error": type(exc).__name__,
        })
        raise


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _record_sync_progress(
    path: Path,
    selected_files: int,
    progress: dict,
    item: dict,
) -> None:
    progress["count"] = int(progress["count"]) + 1
    progress["recent"] = [*progress["recent"], str(item["key"])][-100:]
    _write_state(path, {
        "protocol": DATASET_PROTOCOL, "status": "RUNNING",
        "selected_files": selected_files,
        "completed_count": progress["count"],
        "recent_files": progress["recent"],
    })


def load_active_symbols(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("symbols") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SystemExit("active symbols file must be a list or exchangeInfo object")
    result = set()
    for item in rows:
        if isinstance(item, str):
            result.add(item.upper())
        elif isinstance(item, dict) and item.get("status") == "TRADING":
            symbol = str(item.get("symbol") or "").upper()
            if symbol.endswith("USDT") and "_" not in symbol:
                result.add(symbol)
    return result


def parse_timestamp(value: str) -> int:
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise SystemExit("ISO timestamp must include a timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def verify_native(root: Path, symbol: str, month: str, interval: str) -> dict:
    derived_path = root / "derived" / interval / symbol / f"{symbol}-{interval}-{month}.jsonl.gz"
    if not derived_path.exists():
        raise SystemExit(f"derived partition not found: {derived_path}")
    key = (
        f"data/futures/um/monthly/klines/{symbol}/{interval}/"
        f"{symbol}-{interval}-{month}.zip"
    )
    item = ArchiveObject(
        key=key, size=0, last_modified="", etag=None,
        kind="KLINE_NATIVE_VERIFY", symbol=symbol, month=month,
    )
    native_path = root / "verification" / "native" / interval / symbol / Path(key).name
    ArchiveDownloader().download(item, native_path)
    derived = []
    for row in load_jsonl_gzip(derived_path):
        row["missing_open_times_ms"] = tuple(row.get("missing_open_times_ms") or ())
        derived.append(AggregatedCandle(**row))
    result = compare_native_aggregate(derived, iter_csv_zip_rows(native_path))
    result.update({"symbol": symbol, "month": month, "interval": interval})
    ShortlineDatasetBuilder(root).record_native_verification(result)
    return result


def query_universe(
    root: Path,
    timestamp_ms: int,
    min_history_days: int,
    lookback_days: int,
    minimum_volume: str,
    limit: int | None,
) -> list[str]:
    contracts_payload = json.loads((root / "metadata" / "contracts.json").read_text(encoding="utf-8"))
    liquidity = {}
    for contract in contracts_payload["contracts"]:
        symbol = contract["symbol"]
        rows = []
        for path in sorted((root / "derived" / "daily_liquidity" / symbol).glob("*.jsonl.gz")):
            rows.extend(load_jsonl_gzip(path))
        liquidity[symbol] = rows
    return universe_at(
        timestamp_ms, contracts_payload["contracts"], min_history_days=min_history_days,
        liquidity_by_symbol=liquidity, liquidity_lookback_days=lookback_days,
        min_median_quote_volume=minimum_volume, limit=limit,
    )


def _validate_month(value: str | None) -> None:
    if value is not None and not MONTH_RE.fullmatch(value):
        raise SystemExit(f"invalid month: {value}")


if __name__ == "__main__":
    try:
        main()
    except (ArchiveError, ShortlineDatasetError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"DATA-1R failed: {exc}") from exc
