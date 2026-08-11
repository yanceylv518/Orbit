from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
from typing import Any, Iterable, Sequence
from typing import Callable

from orbit.domain.calibration.shortline_dataset import (
    ArchiveCandle,
    aggregate_candles,
    daily_liquidity,
    infer_contract_metadata,
    validate_candle_sequence,
)
from orbit.domain.calibration.halt_registry import (
    HaltRegistryError,
    entries_by_partition,
    load_halt_registry,
    window_key,
)
from orbit.infrastructure.market_data.binance_public_archive import (
    ArchiveDownloader,
    ArchiveObject,
    archive_destination,
    iter_funding_zip,
    iter_kline_zip,
    sha256_file,
)
from orbit.infrastructure.persistence.atomic_file import replace_with_retry


DATASET_PROTOCOL = "ORBIT_SHORTLINE_DATASET_V1"
NATIVE_ATTESTATION_PROTOCOL = "ORBIT_NATIVE_AGGREGATE_ATTESTATION_V1"
PARTITION_RE = re.compile(r"^(?P<symbol>[A-Z0-9]+USDT)-15m-(?P<month>\d{4}-\d{2})\.zip$")

_IDENTITY_EXCLUDED_FILES = {"manifest.json", "verification_report.json"}
_IDENTITY_EXCLUDED_PREFIXES = ("verification/", "attestations/")


class ShortlineDatasetError(RuntimeError):
    pass


class ShortlineDatasetBuilder:
    def __init__(self, root: Path, halt_registry_path: Path | None = None):
        self.root = root.resolve()
        self.halt_registry_path = (
            halt_registry_path.resolve()
            if halt_registry_path is not None
            else Path(__file__).resolve().parents[4]
            / "config" / "research" / "data1r_halt_registry.v1.json"
        )

    def sync(
        self,
        objects: Sequence[ArchiveObject],
        *,
        workers: int = 4,
        downloader: ArchiveDownloader | None = None,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        if workers < 1 or workers > 16:
            raise ShortlineDatasetError("workers must be between 1 and 16")
        client = downloader or ArchiveDownloader()
        results = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="data1r") as pool:
            futures = {
                pool.submit(client.download, item, archive_destination(self.root, item)): item
                for item in objects
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    raise ShortlineDatasetError(f"failed to sync {item.key}") from exc
                completed = {**result, "key": item.key, "symbol": item.symbol, "month": item.month}
                results.append(completed)
                if on_result is not None:
                    on_result(completed)
        return sorted(results, key=lambda item: item["key"])

    def build(
        self,
        *,
        active_symbols: set[str] | None = None,
        dataset_cutoff_ms: int | None = None,
        allow_partial: bool = False,
        on_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        try:
            halt_registry = load_halt_registry(self.halt_registry_path)
        except HaltRegistryError as exc:
            raise ShortlineDatasetError(str(exc)) from exc
        halt_entries = entries_by_partition(halt_registry)
        partitions = self._kline_partitions()
        if not partitions:
            raise ShortlineDatasetError("no raw 15m archive partitions found")
        coverage = self._archive_coverage(partitions)
        if not coverage["index_available"] and not allow_partial:
            raise ShortlineDatasetError("archive index is required for a complete build")
        if coverage["index_scope"] != "ALL_USDT_PERPETUAL" and not allow_partial:
            raise ShortlineDatasetError(
                "archive index does not cover all historical USD-M perpetual symbols; "
                "use --allow-partial only for sample validation"
            )
        if coverage["missing_partitions"] and not allow_partial:
            raise ShortlineDatasetError(
                f"{len(coverage['missing_partitions'])} indexed 15m partitions are not downloaded; "
                "use --allow-partial only for sample validation"
            )
        if coverage["unexpected_partitions"] and not allow_partial:
            raise ShortlineDatasetError(
                f"{len(coverage['unexpected_partitions'])} local 15m partitions are absent from "
                "the archive index; use --allow-partial only for sample validation"
            )
        partition_quality: list[dict[str, Any]] = []
        contract_quality: list[dict[str, Any]] = []
        verified_halt_windows: list[dict[str, Any]] = []
        invalid_halt_entries: list[dict[str, Any]] = []
        symbol_edges: list[tuple[str, ArchiveCandle, ArchiveCandle]] = []
        latest_close = 0
        ordered_partitions = sorted(partitions.items())
        for position, (symbol, paths) in enumerate(ordered_partitions, start=1):
            symbol_candles: list[ArchiveCandle] = []
            for path in paths:
                candles = list(iter_kline_zip(path))
                sequence = validate_candle_sequence(candles)
                symbol_candles.extend(candles)
                month = PARTITION_RE.fullmatch(path.name).group("month")  # type: ignore[union-attr]
                partition_halts = halt_entries.get((symbol, month), [])
                archive_sha256 = sha256_file(path) if sequence["missing_count"] or partition_halts else None
                missing_by_window = {
                    window_key(item): item for item in sequence["missing_ranges"]
                }
                verified_keys: set[tuple[int, int, int]] = set()
                partition_verified_halts: list[dict[str, Any]] = []
                for entry in partition_halts:
                    key = window_key(entry)
                    if key not in missing_by_window or entry["archive_sha256"] != archive_sha256:
                        invalid_halt_entries.append({
                            "id": entry["id"],
                            "symbol": symbol,
                            "month": month,
                            "reason": (
                                "ARCHIVE_SHA256_MISMATCH"
                                if entry["archive_sha256"] != archive_sha256
                                else "WINDOW_NOT_EXACT"
                            ),
                        })
                        continue
                    verified_keys.add(key)
                    fact = {**entry, "observed_archive_sha256": archive_sha256}
                    partition_verified_halts.append(fact)
                    verified_halt_windows.append(fact)
                unverified_ranges = [
                    item for item in sequence["missing_ranges"]
                    if window_key(item) not in verified_keys
                ]
                self._write_partition(symbol, month, candles)
                partition_quality.append({
                    "symbol": symbol, "month": month, "rows": len(candles),
                    "missing_count": sequence["missing_count"],
                    "missing_ranges": sequence["missing_ranges"],
                    "missing_ranges_truncated": sequence["missing_ranges_truncated"],
                    "duplicate_count": sequence["duplicate_count"],
                    "complete": sequence["complete"],
                    "verified_halt_windows": partition_verified_halts,
                    "unverified_missing_ranges": unverified_ranges,
                    "halt_verified": bool(sequence["missing_count"])
                    and not unverified_ranges
                    and not sequence["missing_ranges_truncated"],
                })
            symbol_candles.sort(key=lambda item: item.open_time_ms)
            sequence = validate_candle_sequence(symbol_candles)
            first = symbol_candles[0]
            last = symbol_candles[-1]
            symbol_edges.append((symbol, first, last))
            latest_close = max(latest_close, last.close_time_ms)
            expected = (
                (last.open_time_ms - first.open_time_ms) // (15 * 60 * 1000) + 1
            )
            contract_quality.append({
                "symbol": symbol,
                "rows": len(symbol_candles),
                "expected_rows_between_first_and_last": expected,
                "coverage_ratio": len({item.open_time_ms for item in symbol_candles}) / expected,
                "missing_count": sequence["missing_count"],
                "missing_ranges": sequence["missing_ranges"],
                "missing_ranges_truncated": sequence["missing_ranges_truncated"],
                "duplicate_count": sequence["duplicate_count"],
                "first_open_time_ms": first.open_time_ms,
                "last_close_time_ms": last.close_time_ms,
            })
            if on_progress is not None:
                on_progress({
                    "completed_symbols": position,
                    "total_symbols": len(ordered_partitions),
                    "current_symbol": symbol,
                })
        if invalid_halt_entries:
            raise ShortlineDatasetError(
                f"{len(invalid_halt_entries)} halt registry entries do not exactly match the "
                "downloaded archive window and SHA-256"
            )
        blocking_partitions = [
            item for item in partition_quality
            if item["duplicate_count"] or item["unverified_missing_ranges"]
            or item["missing_ranges_truncated"]
        ]
        if blocking_partitions and not allow_partial:
            raise ShortlineDatasetError(
                f"{len(blocking_partitions)} downloaded 15m partitions contain unregistered "
                "gaps or duplicates; use --allow-partial only for sample validation"
            )
        cutoff = int(dataset_cutoff_ms if dataset_cutoff_ms is not None else latest_close)
        contracts = [
            infer_contract_metadata(
                symbol,
                (first, last),
                dataset_cutoff_ms=cutoff,
                active_symbols=active_symbols,
                history_complete=coverage["symbol_complete"].get(symbol, False),
            ).as_dict()
            for symbol, first, last in symbol_edges
        ]
        _write_json(self.root / "metadata" / "contracts.json", {
            "protocol": DATASET_PROTOCOL,
            "dataset_cutoff_ms": cutoff,
            "contracts": contracts,
        })
        funding_quality = self._funding_quality()
        verified_halt_windows.sort(
            key=lambda item: (item["symbol"], item["month"], item["start_open_time_ms"])
        )
        _write_json(self.root / "metadata" / "verified_halt_registry.json", {
            "protocol": DATASET_PROTOCOL,
            "halt_registry_protocol": halt_registry["protocol"],
            "halt_registry_version": halt_registry["version"],
            "source_registry_sha256": halt_registry["registry_sha256"],
            "verified_halt_windows": verified_halt_windows,
        })
        quality_core = {
            "protocol": DATASET_PROTOCOL,
            "dataset_cutoff_ms": cutoff,
            "contract_count": len(contracts),
            "partition_count": sum(len(paths) for paths in partitions.values()),
            "dataset_state": (
                "COMPLETE" if coverage["complete"] and not blocking_partitions else "PARTIAL"
            ),
            "halt_registry_sha256": halt_registry["registry_sha256"],
            "verified_halt_windows": verified_halt_windows,
            "archive_coverage": coverage,
            "contracts": contract_quality,
            "partitions": partition_quality,
            "funding": funding_quality,
            "summary": {
                "missing_15m_candles": sum(item["missing_count"] for item in contract_quality),
                "duplicate_15m_candles": sum(item["duplicate_count"] for item in contract_quality),
                "incomplete_15m_partitions": sum(not item["complete"] for item in partition_quality),
                "verified_halt_window_count": len(verified_halt_windows),
                "verified_halt_missing_candles": sum(
                    item["count"] for item in verified_halt_windows
                ),
                "unverified_missing_15m_candles": sum(
                    item["count"]
                    for partition in partition_quality
                    for item in partition["unverified_missing_ranges"]
                ),
                "funding_symbols": len(funding_quality),
                "missing_funding_symbols": sorted(
                    set(partitions) - {item["symbol"] for item in funding_quality}
                ),
            },
        }
        quality_hash = _payload_hash(quality_core)
        quality_report = {**quality_core, "report_sha256": quality_hash}
        _write_json(self.root / "quality_report.json", quality_report)
        manifest = self.build_manifest(dataset_cutoff_ms=cutoff, quality_report_sha256=quality_hash)
        return {"contracts": contracts, "quality_report": quality_report, "manifest": manifest}

    def record_native_verification(
        self,
        result: dict[str, Any],
        *,
        attester_id: str | None = None,
    ) -> dict[str, Any]:
        required = {"symbol", "month", "interval", "compared", "mismatches", "passed"}
        if not required.issubset(result):
            raise ShortlineDatasetError("native verification result is incomplete")
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            raise ShortlineDatasetError("manifest must exist before native verification")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ledger_path = self.root / "attestations" / "native_verification.jsonl"
        self._seed_attestation_ledger_from_legacy_report(
            str(manifest["dataset_fingerprint"])
        )
        existing = _read_jsonl(ledger_path)
        core = {
            "protocol": NATIVE_ATTESTATION_PROTOCOL,
            "sequence": len(existing) + 1,
            "dataset_fingerprint": str(manifest["dataset_fingerprint"]),
            "attester_id": attester_id or platform.node() or "unknown-machine",
            "result": result,
        }
        attestation = {**core, "attestation_sha256": _payload_hash(core)}
        _append_jsonl_atomic(ledger_path, attestation)

        # Compatibility projection for operators. Both this projection and the
        # append-only ledger are evidence about the dataset, never its identity.
        attestations = [*existing, attestation]
        report_core = {
            "protocol": DATASET_PROTOCOL,
            "attestation_protocol": NATIVE_ATTESTATION_PROTOCOL,
            "dataset_fingerprint": str(manifest["dataset_fingerprint"]),
            "attestation_count": len(attestations),
            "samples": [item["result"] for item in attestations],
        }
        _write_json(
            self.root / "verification_report.json",
            {**report_core, "report_sha256": _payload_hash(report_core)},
        )
        return attestation

    def migrate_manifest_identity(self) -> dict[str, Any]:
        """Remove validation evidence from the content identity without touching data."""
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            raise ShortlineDatasetError("manifest does not exist")
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        before_partitions = _partition_hashes(previous.get("entries") or [])
        migrated = self.build_manifest(
            dataset_cutoff_ms=int(previous["dataset_cutoff_ms"]),
            quality_report_sha256=str(previous["quality_report_sha256"]),
            write=False,
        )
        after_partitions = _partition_hashes(migrated["entries"])
        if before_partitions != after_partitions:
            raise ShortlineDatasetError("manifest migration changed data partition hashes")
        imported = self._seed_attestation_ledger_from_legacy_report(
            str(migrated["dataset_fingerprint"])
        )
        _write_json(manifest_path, migrated)
        return {
            "protocol": DATASET_PROTOCOL,
            "previous_fingerprint": previous.get("dataset_fingerprint"),
            "dataset_fingerprint": migrated["dataset_fingerprint"],
            "partition_count": len(after_partitions),
            "partitions_unchanged": True,
            "legacy_attestations_imported": imported,
        }

    def _seed_attestation_ledger_from_legacy_report(
        self,
        dataset_fingerprint: str,
    ) -> int:
        ledger_path = self.root / "attestations" / "native_verification.jsonl"
        if ledger_path.exists():
            return 0
        report_path = self.root / "verification_report.json"
        if not report_path.exists():
            return 0
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("attestation_protocol") == NATIVE_ATTESTATION_PROTOCOL:
            return 0
        samples = report.get("samples") or []
        for sequence, result in enumerate(samples, 1):
            core = {
                "protocol": NATIVE_ATTESTATION_PROTOCOL,
                "sequence": sequence,
                "dataset_fingerprint": dataset_fingerprint,
                "attester_id": "legacy-verification-report",
                "legacy_result_sha256": _payload_hash(result),
                "result": result,
            }
            _append_jsonl_atomic(
                ledger_path,
                {**core, "attestation_sha256": _payload_hash(core)},
            )
        return len(samples)

    def build_manifest(
        self,
        *,
        dataset_cutoff_ms: int,
        quality_report_sha256: str,
        write: bool = True,
    ) -> dict[str, Any]:
        entries = []
        for path in sorted(self.root.rglob("*")):
            if (
                not path.is_file()
                or path.name.endswith(".part")
                or path.name in _IDENTITY_EXCLUDED_FILES
                or path.name in {"dataset_job.lock", "dataset_job_lock.json"}
                or path.name.endswith("_state.json")
            ):
                continue
            relative = path.relative_to(self.root).as_posix()
            if relative.startswith(_IDENTITY_EXCLUDED_PREFIXES):
                continue
            entries.append({
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "kind": _file_kind(relative),
            })
        fingerprint = _payload_hash(entries)
        quality_report = json.loads(
            (self.root / "quality_report.json").read_text(encoding="utf-8")
        )
        manifest = {
            "protocol": DATASET_PROTOCOL,
            "raw_interval": "15m",
            "derived_intervals": ["1h", "4h"],
            "dataset_cutoff_ms": dataset_cutoff_ms,
            "quality_report_sha256": quality_report_sha256,
            "dataset_state": quality_report.get("dataset_state", "UNKNOWN"),
            "halt_registry_sha256": quality_report.get("halt_registry_sha256"),
            "verified_halt_windows": quality_report.get("verified_halt_windows", []),
            "identity_scope": "DATA_CONTENT_QUALITY_AND_HALT_REGISTRY_ONLY",
            "validation_attestations_in_identity": False,
            "entries": entries,
            "dataset_fingerprint": fingerprint,
        }
        if write:
            _write_json(self.root / "manifest.json", manifest)
        return manifest

    def _write_partition(
        self,
        symbol: str,
        month: str,
        candles: Sequence[ArchiveCandle],
    ) -> None:
        for interval in ("1h", "4h"):
            path = self.root / "derived" / interval / symbol / f"{symbol}-{interval}-{month}.jsonl.gz"
            _write_jsonl_gzip(path, (item.as_dict() for item in aggregate_candles(candles, interval)))
        liquidity_path = (
            self.root / "derived" / "daily_liquidity" / symbol
            / f"{symbol}-daily-liquidity-{month}.jsonl.gz"
        )
        _write_jsonl_gzip(liquidity_path, daily_liquidity(candles))

    def _kline_partitions(self) -> dict[str, list[Path]]:
        result: dict[str, list[Path]] = defaultdict(list)
        base = self.root / "raw" / "klines" / "15m"
        if not base.exists():
            return result
        for path in sorted(base.glob("*/*.zip")):
            match = PARTITION_RE.fullmatch(path.name)
            if match and path.parent.name == match.group("symbol"):
                result[match.group("symbol")].append(path)
        return result

    def _archive_coverage(self, partitions: dict[str, list[Path]]) -> dict[str, Any]:
        index_path = self.root / "metadata" / "archive_index.json"
        if not index_path.exists():
            return {
                "index_available": False, "complete": False,
                "index_scope": "MISSING",
                "expected_partitions": 0,
                "downloaded_partitions": sum(len(paths) for paths in partitions.values()),
                "missing_partitions": [],
                "unexpected_partitions": sorted(
                    path.name for paths in partitions.values() for path in paths
                ),
                "symbol_complete": {symbol: False for symbol in partitions},
            }
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        index_scope = str(index_payload.get("scope") or "UNKNOWN")
        objects = load_archive_index(index_path)
        expected = {
            Path(item.key).name: item for item in objects if item.kind == "KLINE_15M"
        }
        downloaded = {
            path.name: path for paths in partitions.values() for path in paths
        }
        missing = sorted(set(expected) - set(downloaded))
        unexpected = sorted(set(downloaded) - set(expected))
        expected_by_symbol: dict[str, set[str]] = defaultdict(set)
        downloaded_by_symbol: dict[str, set[str]] = defaultdict(set)
        for name, item in expected.items():
            expected_by_symbol[item.symbol].add(name)
        for symbol, paths in partitions.items():
            downloaded_by_symbol[symbol].update(path.name for path in paths)
        symbols = set(expected_by_symbol) | set(downloaded_by_symbol)
        symbol_complete = {
            symbol: bool(expected_by_symbol[symbol])
            and expected_by_symbol[symbol] == downloaded_by_symbol[symbol]
            for symbol in symbols
        }
        return {
            "index_available": True,
            "index_scope": index_scope,
            "complete": (
                index_scope == "ALL_USDT_PERPETUAL"
                and not missing and not unexpected and all(symbol_complete.values())
            ),
            "expected_partitions": len(expected),
            "downloaded_partitions": len(downloaded),
            "missing_partitions": missing,
            "unexpected_partitions": unexpected,
            "symbol_complete": symbol_complete,
        }

    def _funding_quality(self) -> list[dict[str, Any]]:
        result = []
        base = self.root / "raw" / "funding"
        if not base.exists():
            return result
        for symbol_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            points = []
            partitions = 0
            for path in sorted(symbol_dir.glob("*.zip")):
                points.extend(iter_funding_zip(path))
                partitions += 1
            points.sort(key=lambda item: item["funding_time_ms"])
            duplicates = len(points) - len({item["funding_time_ms"] for item in points})
            gaps = []
            for previous, current in zip(points, points[1:]):
                expected_ms = int(previous["funding_interval_hours"]) * 60 * 60 * 1000
                tolerance_ms = 60 * 1000
                if (
                    int(current["funding_time_ms"])
                    > int(previous["funding_time_ms"]) + expected_ms + tolerance_ms
                ):
                    gaps.append({
                        "after_ms": int(previous["funding_time_ms"]),
                        "before_ms": int(current["funding_time_ms"]),
                    })
            result.append({
                "symbol": symbol_dir.name, "partitions": partitions, "rows": len(points),
                "duplicate_count": duplicates, "gap_count": len(gaps), "gaps": gaps[:100],
            })
        return result


def load_archive_index(path: Path) -> list[ArchiveObject]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != DATASET_PROTOCOL or not isinstance(payload.get("objects"), list):
        raise ShortlineDatasetError("invalid DATA-1R archive index")
    return [ArchiveObject(**item) for item in payload["objects"]]


def write_archive_index(
    path: Path,
    objects: Sequence[ArchiveObject],
    *,
    scope: str = "UNKNOWN",
) -> dict[str, Any]:
    rows = [item.as_dict() for item in sorted(objects, key=lambda item: item.key)]
    payload = {
        "protocol": DATASET_PROTOCOL,
        "source": "https://data.binance.vision/data/futures/um/monthly",
        "scope": scope,
        "indexed_symbols": sorted({item.symbol for item in objects}),
        "objects_sha256": _payload_hash(rows),
        "objects": rows,
    }
    _write_json(path, payload)
    return payload


def filter_archive_objects(
    objects: Sequence[ArchiveObject],
    *,
    symbols: set[str] | None = None,
    start_month: str | None = None,
    end_month: str | None = None,
    kinds: set[str] | None = None,
) -> list[ArchiveObject]:
    normalized_symbols = {item.upper() for item in symbols} if symbols else None
    return [
        item for item in objects
        if (normalized_symbols is None or item.symbol in normalized_symbols)
        and (start_month is None or item.month >= start_month)
        and (end_month is None or item.month <= end_month)
        and (kinds is None or item.kind in kinds)
    ]


def load_jsonl_gzip(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    _atomic_write_if_changed(path, encoded)


def _write_jsonl_gzip(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    buffer = bytearray()
    for row in rows:
        buffer.extend(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        buffer.extend(b"\n")
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0) as target:
        target.write(buffer)
    _atomic_write_if_changed(path, compressed.getvalue())


def _atomic_write_if_changed(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == content:
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    replace_with_retry(temporary, path)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ShortlineDatasetError(
                f"invalid attestation ledger line {line_number}"
            ) from exc
    return records


def _append_jsonl_atomic(path: Path, record: dict[str, Any]) -> None:
    existing = path.read_bytes() if path.exists() else b""
    if existing and not existing.endswith(b"\n"):
        existing += b"\n"
    line = json.dumps(
        record, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    _atomic_write_if_changed(path, existing + line)


def _partition_hashes(entries: Sequence[dict[str, Any]]) -> dict[str, str]:
    partition_kinds = {
        "RAW_KLINE_15M",
        "RAW_FUNDING",
        "DERIVED_KLINE_1H",
        "DERIVED_KLINE_4H",
        "DAILY_LIQUIDITY",
    }
    return {
        str(item["path"]): str(item["sha256"])
        for item in entries
        if item.get("kind") in partition_kinds
    }


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_kind(relative: str) -> str:
    if relative.startswith("raw/klines/15m/"):
        return "RAW_KLINE_15M"
    if relative.startswith("raw/funding/"):
        return "RAW_FUNDING"
    if relative.startswith("derived/1h/"):
        return "DERIVED_KLINE_1H"
    if relative.startswith("derived/4h/"):
        return "DERIVED_KLINE_4H"
    if relative.startswith("derived/daily_liquidity/"):
        return "DAILY_LIQUIDITY"
    if relative == "metadata/contracts.json":
        return "CONTRACT_METADATA"
    if relative == "metadata/archive_index.json":
        return "ARCHIVE_INDEX"
    if relative == "metadata/verified_halt_registry.json":
        return "VERIFIED_HALT_REGISTRY"
    if relative == "quality_report.json":
        return "QUALITY_REPORT"
    if relative == "verification_report.json":
        return "NATIVE_AGGREGATE_VERIFICATION"
    if relative.startswith("verification/native/"):
        return "NATIVE_KLINE_VERIFICATION_SOURCE"
    return "AUXILIARY"
