from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import RLock
from typing import Any, Literal


DATASET_PROTOCOL = "ORBIT_SHORTLINE_DATASET_V1"
QualityKind = Literal["halts", "missing", "duplicates"]


class DataSummaryError(RuntimeError):
    pass


class DataSummaryService:
    """Read-only projection of the frozen shortline dataset evidence files."""

    def __init__(self, dataset_root: Path):
        self.dataset_root = dataset_root
        self._lock = RLock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._snapshot: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any] | None:
        snapshot = self._load_snapshot()
        return deepcopy(snapshot["summary"]) if snapshot else None

    def quality_page(
        self,
        kind: QualityKind,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any] | None:
        snapshot = self._load_snapshot()
        if not snapshot:
            return None
        items = snapshot["quality_items"][kind]
        start = (page - 1) * page_size
        return {
            "dataset_id": snapshot["summary"]["dataset_id"],
            "dataset_fingerprint": snapshot["summary"]["dataset_fingerprint"],
            "kind": kind,
            "page": page,
            "page_size": page_size,
            "total": len(items),
            "items": deepcopy(items[start:start + page_size]),
        }

    def _load_snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            signature = self._file_signature()
            if not signature:
                self._signature = None
                self._snapshot = None
                return None
            if signature == self._signature and self._snapshot is not None:
                return self._snapshot
            snapshot = self._read_snapshot()
            signature_after_read = self._file_signature()
            if signature_after_read == signature:
                self._signature = signature
                self._snapshot = snapshot
            else:
                self._signature = None
                self._snapshot = None
            return snapshot

    def _read_snapshot(self) -> dict[str, Any]:
        manifest = self._read_json("manifest.json")
        quality = self._read_json("quality_report.json")
        contracts_payload = self._read_json("metadata/contracts.json")
        for label, payload in (
            ("manifest", manifest),
            ("quality report", quality),
            ("contract metadata", contracts_payload),
        ):
            if payload.get("protocol") != DATASET_PROTOCOL:
                raise DataSummaryError(f"{label} protocol is invalid")
        if quality.get("report_sha256") != manifest.get("quality_report_sha256"):
            raise DataSummaryError("quality report fingerprint does not match manifest")
        cutoff = int(manifest.get("dataset_cutoff_ms") or 0)
        if cutoff <= 0 or int(quality.get("dataset_cutoff_ms") or 0) != cutoff:
            raise DataSummaryError("dataset cutoff is inconsistent")
        if int(contracts_payload.get("dataset_cutoff_ms") or 0) != cutoff:
            raise DataSummaryError("contract metadata cutoff is inconsistent")

        contracts = contracts_payload.get("contracts") or []
        trading = sum(item.get("status") == "TRADING" for item in contracts)
        delisted = sum(item.get("status") == "DELISTED" for item in contracts)
        quality_summary = quality.get("summary") or {}
        verified_halts = quality.get("verified_halt_windows") or []
        quality_items = {
            "halts": [self._halt_item(item) for item in verified_halts],
            "missing": self._missing_items(quality, verified_halts),
            "duplicates": self._duplicate_items(quality),
        }
        summary = {
            "dataset_id": self.dataset_root.name,
            "dataset_state": manifest.get("dataset_state"),
            "dataset_cutoff_ms": cutoff,
            "dataset_fingerprint": manifest.get("dataset_fingerprint"),
            "quality_report_sha256": quality.get("report_sha256"),
            "contracts": {
                "total": int(quality.get("contract_count") or len(contracts)),
                "trading": trading,
                "delisted": delisted,
            },
            "coverage": {
                "partitions": int(quality.get("partition_count") or 0),
                "archive_complete": bool((quality.get("archive_coverage") or {}).get("complete")),
            },
            "quality": {
                "missing_15m_candles": int(quality_summary.get("missing_15m_candles") or 0),
                "unverified_missing_15m_candles": int(
                    quality_summary.get("unverified_missing_15m_candles") or 0
                ),
                "duplicate_15m_candles": int(quality_summary.get("duplicate_15m_candles") or 0),
                "verified_halt_windows": int(quality_summary.get("verified_halt_window_count") or 0),
                "verified_halt_missing_candles": int(
                    quality_summary.get("verified_halt_missing_candles") or 0
                ),
                "incomplete_15m_partitions": int(
                    quality_summary.get("incomplete_15m_partitions") or 0
                ),
                "funding_symbols": int(quality_summary.get("funding_symbols") or 0),
                "missing_funding_symbols": len(quality_summary.get("missing_funding_symbols") or []),
            },
        }
        return {"summary": summary, "quality_items": quality_items}

    def _read_json(self, relative_path: str) -> dict[str, Any]:
        path = self.dataset_root / relative_path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataSummaryError(f"cannot read {relative_path}") from exc
        if not isinstance(payload, dict):
            raise DataSummaryError(f"{relative_path} must contain an object")
        return payload

    def _file_signature(self) -> tuple[tuple[str, int, int], ...]:
        signature = []
        for relative_path in ("manifest.json", "quality_report.json", "metadata/contracts.json"):
            path = self.dataset_root / relative_path
            try:
                stat = path.stat()
            except OSError:
                return ()
            signature.append((relative_path, stat.st_size, stat.st_mtime_ns))
        return tuple(signature)

    @staticmethod
    def _halt_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "symbol": item.get("symbol"),
            "month": item.get("month"),
            "start_open_time_ms": item.get("start_open_time_ms"),
            "end_open_time_ms": item.get("end_open_time_ms"),
            "missing_candles": int(item.get("count") or 0),
            "classification": item.get("classification"),
        }

    @staticmethod
    def _missing_items(
        quality: dict[str, Any],
        verified_halts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        verified = {
            (
                item.get("symbol"),
                item.get("month"),
                item.get("start_open_time_ms"),
                item.get("end_open_time_ms"),
            )
            for item in verified_halts
        }
        items = []
        for partition in quality.get("partitions") or []:
            for window in partition.get("missing_ranges") or []:
                key = (
                    partition.get("symbol"),
                    partition.get("month"),
                    window.get("start_open_time_ms"),
                    window.get("end_open_time_ms"),
                )
                items.append({
                    "symbol": partition.get("symbol"),
                    "month": partition.get("month"),
                    "start_open_time_ms": window.get("start_open_time_ms"),
                    "end_open_time_ms": window.get("end_open_time_ms"),
                    "missing_candles": int(window.get("count") or 0),
                    "explained_by_halt": key in verified,
                })
        return items

    @staticmethod
    def _duplicate_items(quality: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "symbol": item.get("symbol"),
                "month": item.get("month"),
                "duplicate_candles": int(item.get("duplicate_count") or 0),
            }
            for item in quality.get("partitions") or []
            if int(item.get("duplicate_count") or 0) > 0
        ]
