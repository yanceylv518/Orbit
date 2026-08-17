"""Build the survivorship-safe DATA-1R research dataset from Binance public archives.

The default dataset root is isolated from TB4 and existing calibration caches:
``var/calibration/shortline-data-v1``. Network commands never require credentials.
"""

from __future__ import annotations

import argparse
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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
from orbit.infrastructure.persistence.dataset_job_lock import (  # noqa: E402
    DatasetJobLock,
    DatasetJobLockBusy,
)
from orbit.infrastructure.persistence.atomic_file import replace_with_retry  # noqa: E402


MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DEFAULT_ROOT = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--lock-owner-token", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="Enumerate all historical USD-M archive objects")
    index.add_argument("--no-funding", action="store_true")
    index.add_argument("--symbol", action="append", default=[])

    update_index = commands.add_parser(
        "update-index", help="Check only unpublished daily partitions after the dataset cutoff",
    )
    update_index.add_argument("--workers", type=int, default=8)

    sync = commands.add_parser("sync", help="Download checksum-verified raw partitions")
    sync.add_argument("--symbol", action="append", default=[])
    sync.add_argument("--start-month")
    sync.add_argument("--end-month")
    sync.add_argument("--kind", action="append", choices=["KLINE_15M", "FUNDING"])
    sync.add_argument("--workers", type=int, default=4)
    sync.add_argument("--max-files", type=int)
    sync.add_argument("--confirm-full-download", action="store_true")

    sync_update = commands.add_parser("sync-update", help="Download only planned daily additions")
    sync_update.add_argument("--workers", type=int, default=4)

    commands.add_parser("build-update", help="Build only newly downloaded daily partitions")

    build = commands.add_parser("build", help="Build 1h/4h, liquidity, metadata and manifest")
    build.add_argument("--active-symbols-file")
    build.add_argument("--dataset-cutoff")
    build.add_argument("--allow-partial", action="store_true")

    verify = commands.add_parser("verify-native", help="Compare local aggregates with native archive")
    verify.add_argument("--symbol", required=True)
    verify.add_argument("--month", required=True)
    verify.add_argument("--interval", required=True, choices=["1h", "4h"])

    verify_batch = commands.add_parser(
        "verify-batch", help="Verify deterministic native 1h/4h samples",
    )
    verify_batch.add_argument("--sample-symbols", type=int, default=3)

    commands.add_parser(
        "migrate-manifest",
        help="Separate stable data identity from validation attestations",
    )

    query = commands.add_parser("universe", help="Query the point-in-time liquidity universe")
    query.add_argument("--timestamp", required=True)
    query.add_argument("--min-history-days", type=int, default=30)
    query.add_argument("--lookback-days", type=int, default=7)
    query.add_argument("--min-median-quote-volume", default="0")
    query.add_argument("--limit", type=int)

    args = parser.parse_args()
    root = validated_dataset_root(Path(args.root))
    if args.command != "universe":
        if args.lock_owner_token:
            DatasetJobLock.validate_token(root, args.lock_owner_token)
        else:
            command_lock = DatasetJobLock(root, owner=f"cli:{args.command}")
            command_lock.acquire()
            atexit.register(command_lock.release)
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
    elif args.command == "update-index":
        payload = build_incremental_archive_index(root, workers=args.workers)
        print(json.dumps(payload, ensure_ascii=False))
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
        total_bytes = sum(max(int(item.size), 0) for item in objects)
        sizes_by_key = {item.key: max(int(item.size), 0) for item in objects}
        sync_progress = {"count": 0, "bytes": 0, "recent": [], "errors": 0}
        _write_state(sync_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "RUNNING",
            "selected_files": len(objects), "completed_count": 0, "recent_files": [],
            "total_bytes": total_bytes, "completed_bytes": 0,
            "error_count": 0, "recent_logs": ["下载任务已启动"],
        })
        try:
            results = ShortlineDatasetBuilder(root).sync(
                objects, workers=args.workers,
                on_result=lambda item: _record_sync_progress(
                    sync_state_path, len(objects), total_bytes, sizes_by_key,
                    sync_progress, item,
                ),
            )
        except BaseException as exc:
            sync_progress["errors"] = int(sync_progress["errors"]) + 1
            _write_state(sync_state_path, {
                "protocol": DATASET_PROTOCOL,
                "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                "selected_files": len(objects),
                "completed_count": sync_progress["count"],
                "recent_files": sync_progress["recent"],
                "total_bytes": total_bytes, "completed_bytes": sync_progress["bytes"],
                "error_count": sync_progress["errors"],
                "recent_logs": [*sync_progress["recent"][-4:], f"失败：{type(exc).__name__}"],
                "error": type(exc).__name__,
            })
            raise
        _write_state(sync_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
            "selected_files": len(objects),
            "completed_count": sync_progress["count"],
            "recent_files": sync_progress["recent"],
            "total_bytes": total_bytes, "completed_bytes": sync_progress["bytes"],
            "error_count": sync_progress["errors"],
            "recent_logs": [*sync_progress["recent"][-4:], "下载与 checksum 校验完成"],
        })
        print(json.dumps({
            "files": len(results),
            "downloaded": sum(item["status"] == "DOWNLOADED" for item in results),
            "unchanged": sum(item["status"] == "UNCHANGED" for item in results),
        }, ensure_ascii=False))
    elif args.command == "sync-update":
        plan_path = root / "metadata" / "incremental_update.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        objects = [ArchiveObject(**item) for item in plan.get("pending_objects") or []]
        total_bytes = sum(max(int(obj.size), 0) for obj in objects)
        sizes_by_key = {obj.key: max(int(obj.size), 0) for obj in objects}
        sync_progress = {"count": 0, "bytes": 0, "recent": [], "errors": 0}
        _write_state(root / "metadata" / "sync_state.json", {
            "protocol": DATASET_PROTOCOL, "status": "RUNNING",
            "selected_files": len(objects), "completed_count": 0,
            "recent_files": [], "total_bytes": total_bytes,
            "completed_bytes": 0, "error_count": 0,
            "recent_logs": ["增量下载任务已启动"],
        })
        results = ShortlineDatasetBuilder(root).sync(
            objects, workers=args.workers,
            on_result=lambda item: _record_sync_progress(
                root / "metadata" / "sync_state.json", len(objects),
                total_bytes, sizes_by_key,
                sync_progress, item,
            ),
        ) if objects else []
        _write_state(root / "metadata" / "sync_state.json", {
            "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
            "selected_files": len(objects), "completed_count": len(results),
            "recent_files": sync_progress["recent"], "total_bytes": total_bytes,
            "completed_bytes": sync_progress["bytes"], "error_count": sync_progress["errors"],
            "recent_logs": [
                "没有新增文件" if not objects
                else f"增量下载完成，{sync_progress['errors']} 个文件失败" if sync_progress["errors"]
                else "增量下载完成"
            ],
        })
        print(json.dumps({
            "files": len(results),
            "downloaded": sum(item["status"] == "DOWNLOADED" for item in results),
            "unchanged": sum(item["status"] == "UNCHANGED" for item in results),
        }, ensure_ascii=False))
    elif args.command == "build-update":
        plan = json.loads(
            (root / "metadata" / "incremental_update.json").read_text(encoding="utf-8")
        )
        objects = [ArchiveObject(**item) for item in plan.get("pending_objects") or []]
        result = ShortlineDatasetBuilder(root).build_incremental(objects)
        plan.update({
            "status": "COMPLETE", "added_partitions": result["added_partitions"],
            "dataset_cutoff_ms": result["manifest"]["dataset_cutoff_ms"],
        })
        _write_state(root / "metadata" / "incremental_update.json", plan)
        print(json.dumps({
            "contracts": len(result["contracts"]),
            "added_partitions": result["added_partitions"],
            "dataset_cutoff_ms": result["manifest"]["dataset_cutoff_ms"],
            "dataset_fingerprint": result["manifest"]["dataset_fingerprint"],
            "quality_report_sha256": result["quality_report"]["report_sha256"],
            "dataset_state": result["quality_report"]["dataset_state"],
        }, ensure_ascii=False))
    elif args.command == "build":
        active = load_active_symbols(Path(args.active_symbols_file)) if args.active_symbols_file else None
        cutoff = parse_timestamp(args.dataset_cutoff) if args.dataset_cutoff else None
        build_state_path = root / "metadata" / "build_state.json"
        _write_state(build_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "RUNNING",
            "allow_partial": bool(args.allow_partial),
            "completed_symbols": 0, "total_symbols": 0,
            "current_symbol": None, "error_count": 0,
            "recent_logs": ["派生数据构建已启动"],
        })
        try:
            result = ShortlineDatasetBuilder(root).build(
                active_symbols=active, dataset_cutoff_ms=cutoff,
                allow_partial=args.allow_partial,
                on_progress=lambda item: _record_build_progress(
                    build_state_path, bool(args.allow_partial), item,
                ),
            )
        except BaseException as exc:
            _write_state(build_state_path, {
                "protocol": DATASET_PROTOCOL,
                "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
                "allow_partial": bool(args.allow_partial), "error": type(exc).__name__,
                "error_count": 1, "recent_logs": [f"构建失败：{type(exc).__name__}"],
            })
            raise
        _write_state(build_state_path, {
            "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
            "allow_partial": bool(args.allow_partial),
            "dataset_state": result["quality_report"]["dataset_state"],
            "dataset_fingerprint": result["manifest"]["dataset_fingerprint"],
            "completed_symbols": len(result["contracts"]),
            "total_symbols": len(result["contracts"]), "current_symbol": None,
            "error_count": 0, "recent_logs": ["派生数据与质量报告构建完成"],
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
    elif args.command == "verify-batch":
        if not 1 <= args.sample_symbols <= 20:
            raise SystemExit("--sample-symbols must be between 1 and 20")
        result = verify_native_batch(root, args.sample_symbols)
        print(json.dumps(result, ensure_ascii=False))
        if not result["passed"]:
            raise SystemExit(2)
    elif args.command == "migrate-manifest":
        result = ShortlineDatasetBuilder(root).migrate_manifest_identity()
        print(json.dumps(result, ensure_ascii=False))
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
                "error_count": 0, "recent_logs": [f"正在枚举 {symbol}"],
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
            "error_count": 0, "recent_logs": [f"已枚举 {len(completed)} 个合约"],
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
            "error_count": 1, "recent_logs": [f"枚举失败：{type(exc).__name__}"],
            "error": type(exc).__name__,
        })
        raise


def build_incremental_archive_index(root: Path, *, workers: int = 8) -> dict:
    if workers < 1 or workers > 16:
        raise SystemExit("--workers must be between 1 and 16")
    index_path = root / "metadata" / "archive_index.json"
    manifest_path = root / "manifest.json"
    if not index_path.exists() or not manifest_path.exists():
        raise SystemExit("incremental update requires an existing complete dataset")
    existing = load_archive_index(index_path)
    existing_payload = json.loads(index_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cutoff_ms = int(manifest.get("dataset_cutoff_ms") or 0)
    if cutoff_ms <= 0:
        raise SystemExit("existing dataset cutoff is missing")
    cutoff_day = datetime.fromtimestamp(cutoff_ms / 1000, tz=timezone.utc).date()
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    months = []
    cursor = cutoff_day.replace(day=1)
    while cursor <= yesterday:
        months.append(cursor.strftime("%Y-%m"))
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    client = BinancePublicArchiveIndex()
    symbols = client.discover_daily_symbols()
    discovered: list[ArchiveObject] = []
    jobs = [(symbol, month) for symbol in symbols for month in months]
    state_path = root / "metadata" / "archive_index_state.json"
    completed_symbols: set[str] = set()
    _write_state(state_path, {
        "protocol": DATASET_PROTOCOL, "status": "RUNNING",
        "total_symbols": len(symbols), "completed_symbols": [],
        "current_symbol": None, "error_count": 0,
        "recent_logs": ["正在检查日度增量"],
    })
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="data1r-index") as pool:
        futures = {
            pool.submit(client.discover_daily_symbol_month, symbol, month): (symbol, month)
            for symbol, month in jobs
        }
        for future in as_completed(futures):
            symbol, _month = futures[future]
            discovered.extend(future.result())
            completed_symbols.add(symbol)
            _write_state(state_path, {
                "protocol": DATASET_PROTOCOL, "status": "RUNNING",
                "total_symbols": len(symbols),
                "completed_symbols": sorted(completed_symbols),
                "current_symbol": symbol, "error_count": 0,
                "recent_logs": [f"已检查 {symbol}"],
            })
    eligible = [
        item for item in discovered
        if cutoff_day.isoformat() < item.month <= yesterday.isoformat()
    ]
    existing_keys = {item.key for item in existing}
    pending = sorted((
        item for item in eligible
        if item.key not in existing_keys
        or not (root / "raw" / "klines" / "15m" / item.symbol / Path(item.key).name).exists()
        or not (
            root / "derived" / "1h" / item.symbol
            / f"{item.symbol}-1h-{item.month}.jsonl.gz"
        ).exists()
    ), key=lambda x: x.key)
    merged = {item.key: item for item in existing}
    merged.update({item.key: item for item in pending})
    write_archive_index(
        index_path, list(merged.values()),
        scope=str(existing_payload.get("scope") or "ALL_USDT_PERPETUAL"),
    )
    plan = {
        "protocol": DATASET_PROTOCOL,
        "checked_through": yesterday.isoformat(),
        "previous_cutoff_ms": cutoff_ms,
        "pending_objects": [item.as_dict() for item in pending],
        "pending_files": len(pending),
        "affected_symbols": sorted({item.symbol for item in pending}),
    }
    _write_state(root / "metadata" / "incremental_update.json", plan)
    _write_state(state_path, {
        "protocol": DATASET_PROTOCOL, "status": "COMPLETE",
        "total_symbols": len(symbols), "completed_symbols": symbols,
        "current_symbol": None, "error_count": 0,
        "recent_logs": [
            f"发现 {len(pending)} 个新增日分区" if pending else "没有新增日分区"
        ],
    })
    return plan


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    replace_with_retry(temporary, path)


def _record_sync_progress(
    path: Path,
    selected_files: int,
    total_bytes: int,
    sizes_by_key: dict[str, int],
    progress: dict,
    item: dict,
) -> None:
    progress["count"] = int(progress["count"]) + 1
    progress["bytes"] = int(progress["bytes"]) + sizes_by_key.get(str(item["key"]), 0)
    progress["recent"] = [*progress["recent"], str(item["key"])][-100:]
    _write_state(path, {
        "protocol": DATASET_PROTOCOL, "status": "RUNNING",
        "selected_files": selected_files,
        "completed_count": progress["count"],
        "recent_files": progress["recent"],
        "total_bytes": total_bytes, "completed_bytes": progress["bytes"],
        "error_count": progress["errors"],
        "recent_logs": progress["recent"][-5:],
    })


def _record_build_progress(path: Path, allow_partial: bool, item: dict) -> None:
    _write_state(path, {
        "protocol": DATASET_PROTOCOL, "status": "RUNNING",
        "allow_partial": allow_partial,
        "completed_symbols": item["completed_symbols"],
        "total_symbols": item["total_symbols"],
        "current_symbol": item["current_symbol"],
        "error_count": 0,
        "recent_logs": [f"已处理 {item['current_symbol']}"],
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
    granularity = "daily" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", month) else "monthly"
    key = (
        f"data/futures/um/{granularity}/klines/{symbol}/{interval}/"
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


def verify_native_batch(root: Path, sample_symbols: int) -> dict:
    candidates: dict[str, list[str]] = {}
    base = root / "derived" / "1h"
    for symbol_dir in sorted(base.glob("*USDT")):
        months = sorted(
            path.name.removeprefix(f"{symbol_dir.name}-1h-").removesuffix(".jsonl.gz")
            for path in symbol_dir.glob(f"{symbol_dir.name}-1h-*.jsonl.gz")
        )
        if months:
            candidates[symbol_dir.name] = months
    if not candidates:
        raise ShortlineDatasetError("no derived partitions are available for native verification")
    ordered = sorted(candidates)
    preferred = [symbol for symbol in ("LUNAUSDT", "BTCUSDT") if symbol in candidates]
    selected = [*preferred, *[symbol for symbol in ordered if symbol not in preferred]][:sample_symbols]
    jobs = [
        (symbol, candidates[symbol][-1], interval)
        for symbol in selected
        for interval in ("1h", "4h")
    ]
    state_path = root / "metadata" / "verification_state.json"
    samples = []
    _write_state(state_path, {
        "protocol": DATASET_PROTOCOL, "status": "RUNNING",
        "total_samples": len(jobs), "completed_samples": 0,
        "current_item": None, "error_count": 0,
        "recent_logs": ["原生聚合抽样开始"],
    })
    try:
        for symbol, month, interval in jobs:
            current = f"{symbol}/{month}/{interval}"
            _write_state(state_path, {
                "protocol": DATASET_PROTOCOL, "status": "RUNNING",
                "total_samples": len(jobs), "completed_samples": len(samples),
                "current_item": current, "error_count": 0,
                "recent_logs": [f"正在核对 {current}"],
            })
            result = verify_native(root, symbol, month, interval)
            samples.append(result)
    except BaseException as exc:
        _write_state(state_path, {
            "protocol": DATASET_PROTOCOL,
            "status": "CANCELLED" if isinstance(exc, KeyboardInterrupt) else "FAILED",
            "total_samples": len(jobs), "completed_samples": len(samples),
            "current_item": current, "error_count": 1,
            "recent_logs": [f"核对失败：{current}"], "error": type(exc).__name__,
        })
        raise
    passed = all(item["passed"] for item in samples)
    _write_state(state_path, {
        "protocol": DATASET_PROTOCOL, "status": "COMPLETE" if passed else "FAILED",
        "total_samples": len(jobs), "completed_samples": len(samples),
        "current_item": None, "error_count": sum(not item["passed"] for item in samples),
        "recent_logs": [f"已完成 {len(samples)} 个原生聚合抽样"],
    })
    return {"passed": passed, "samples": samples, "sample_count": len(samples)}


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
    except (
        ArchiveError, DatasetJobLockBusy, ShortlineDatasetError,
        OSError, ValueError, json.JSONDecodeError,
    ) as exc:
        raise SystemExit(f"DATA-1R failed: {exc}") from exc
