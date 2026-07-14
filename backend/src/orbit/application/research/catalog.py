from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from orbit.application.research.candidates import INITIAL_CANDIDATES


MARKET_RE = re.compile(r"([A-Z0-9]+USDT)", re.IGNORECASE)
INTERVAL_RE = re.compile(r"(?:^|_)(1m|3m|5m|15m|30m|1h|4h|1d)(?:_|$)", re.IGNORECASE)
TIME_KEYS = ("close_time_ms", "funding_time_ms", "timestamp", "time_ms", "open_time")


class ResearchCatalogService:
    def __init__(self, calibration_dir: Path, registry: Any, run_ledger: Any | None = None):
        self.calibration_dir = calibration_dir
        self.registry = registry
        self.run_ledger = run_ledger

    def datasets(self) -> list[dict[str, Any]]:
        items = []
        if not self.calibration_dir.exists():
            return items
        for path in sorted(self.calibration_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, list):
                continue
            first = payload[0] if payload else None
            last = payload[-1] if payload else None
            market = MARKET_RE.search(path.stem)
            interval = INTERVAL_RE.search(path.stem)
            kind = self._dataset_kind(path, first)
            items.append({
                "id": path.stem,
                "market": market.group(1).upper() if market else None,
                "interval": interval.group(1).lower() if interval else None,
                "kind": kind,
                "rows": len(payload),
                "start_time_ms": self._time_value(first),
                "end_time_ms": self._time_value(last),
                "sha256": self._sha256(path),
                "size_bytes": path.stat().st_size,
                "relative_path": f"var/calibration/{path.name}",
            })
        return items

    def candidates(self) -> list[dict[str, Any]]:
        self.registry.ensure(INITIAL_CANDIDATES)
        results = self._result_index()
        return [self._candidate_view(item, results) for item in self.registry.all()]

    def datasets_by_ids(self, dataset_ids: list[str]) -> list[dict[str, Any]]:
        index = {item["id"]: item for item in self.datasets()}
        missing = [dataset_id for dataset_id in dataset_ids if dataset_id not in index]
        if missing:
            raise ValueError(f"cached research datasets not found: {', '.join(missing)}")
        return [index[dataset_id] for dataset_id in dataset_ids]

    def candidate(self, candidate_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self.candidates() if item["id"].lower() == candidate_id.lower()),
            None,
        )

    def result(self, result_id: str) -> dict[str, Any] | None:
        path = self._result_index().get(result_id)
        if not path:
            return None
        report = json.loads(path.read_text(encoding="utf-8"))
        candidate = self._candidate_for_result(result_id)
        return {
            "id": path.stem,
            "sha256": self._sha256(path),
            "size_bytes": path.stat().st_size,
            "relative_path": f"var/calibration/{path.name}",
            "protocol": report.get("protocol") or (candidate["id"] if candidate else None),
            "verdict": report.get("verdict") or (candidate["verdict"] if candidate else None),
            "evidence_level": report.get("evidence_level"),
            "generated_at": report.get("generated_at"),
            "report": report,
        }

    def _result_index(self) -> dict[str, Path]:
        if not self.calibration_dir.exists():
            return {}
        index = {}
        for path in sorted(self.calibration_dir.glob("*.json")):
            try:
                with path.open("r", encoding="utf-8") as source:
                    first = source.read(64).lstrip()
            except OSError:
                continue
            if first.startswith("{"):
                index[path.stem] = path
        return index

    def _candidate_view(self, candidate: dict[str, Any], results: dict[str, Path]) -> dict[str, Any]:
        runs = self.run_ledger.for_candidate(candidate["id"]) if self.run_ledger else []
        run_results = [item["result_id"] for item in runs if item.get("result_id")]
        result_ids = [*run_results, *candidate["result_ids"]]
        latest_completed = next((item for item in runs if item.get("verdict")), None)
        lockbox_run = next((item for item in reversed(runs) if item.get("lockbox_opened_at")), None)
        return {
            **candidate,
            "latest_verdict": latest_completed.get("verdict") if latest_completed else candidate["verdict"],
            "effective_lockbox_opened_at": (
                lockbox_run.get("lockbox_opened_at") if lockbox_run else candidate["lockbox_opened_at"]
            ),
            "runs": runs,
            "results": [
                {
                    "id": result_id,
                    "available": result_id in results,
                }
                for result_id in result_ids
            ],
        }

    def _candidate_for_result(self, result_id: str) -> dict[str, Any] | None:
        candidate = next(
            (candidate for candidate in INITIAL_CANDIDATES if result_id in candidate["result_ids"]),
            None,
        )
        if candidate or not self.run_ledger:
            return candidate
        run = self.run_ledger.by_result(result_id)
        return self.candidate(run["candidate_id"]) if run else None

    @staticmethod
    def _dataset_kind(path: Path, first: Any) -> str:
        if "funding" in path.stem.lower() or isinstance(first, dict) and "funding_rate" in first:
            return "funding"
        if isinstance(first, dict) and "close" in first:
            return "ohlc"
        return "series"

    @staticmethod
    def _time_value(row: Any) -> int | None:
        if isinstance(row, dict):
            for key in TIME_KEYS:
                if row.get(key) is not None:
                    try:
                        return int(row[key])
                    except (TypeError, ValueError):
                        return None
        if isinstance(row, list) and row:
            try:
                return int(row[0])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
