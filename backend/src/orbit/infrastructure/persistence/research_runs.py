from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from orbit.application.research.candidates import canonical_json
from orbit.infrastructure.persistence.research_registry import GENESIS_HASH


class AppendOnlyResearchRunLedger:
    """Hash-chained event ledger. Run state is projected from append-only events."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = RLock()

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            records = self._records()
            previous_hash = records[-1]["record_hash"] if records else GENESIS_HASH
            body = {
                "sequence": len(records) + 1,
                "previous_hash": previous_hash,
                "event": dict(event),
            }
            record = body | {"record_hash": hashlib.sha256(canonical_json(body)).hexdigest()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as target:
                target.write(canonical_json(record).decode("utf-8") + "\n")
                target.flush()
                os.fsync(target.fileno())
            return dict(event)

    def runs(self) -> list[dict[str, Any]]:
        projected: dict[str, dict[str, Any]] = {}
        for record in self._records():
            event = record["event"]
            run_id = str(event["id"])
            if run_id not in projected:
                projected[run_id] = dict(event)
            else:
                current = projected[run_id]
                for immutable in ("id", "candidate_id", "candidate_hash", "protocol", "created_at"):
                    if event.get(immutable, current.get(immutable)) != current.get(immutable):
                        raise RuntimeError(f"research run immutable field changed: {immutable}")
                current.update(event)
        return sorted(projected.values(), key=lambda item: str(item["created_at"]), reverse=True)

    def get(self, run_id: str) -> dict[str, Any] | None:
        return next((item for item in self.runs() if item["id"] == run_id), None)

    def for_candidate(self, candidate_id: str) -> list[dict[str, Any]]:
        return [item for item in self.runs() if item["candidate_id"].lower() == candidate_id.lower()]

    def by_result(self, result_id: str) -> dict[str, Any] | None:
        return next((item for item in self.runs() if item.get("result_id") == result_id), None)

    def _records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records = []
        previous_hash = GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as source:
            for line_number, raw in enumerate(source, start=1):
                if not raw.strip():
                    continue
                record = json.loads(raw)
                body = {
                    "sequence": record.get("sequence"),
                    "previous_hash": record.get("previous_hash"),
                    "event": record.get("event"),
                }
                expected = hashlib.sha256(canonical_json(body)).hexdigest()
                if body["sequence"] != len(records) + 1:
                    raise RuntimeError(f"research run sequence mismatch at line {line_number}")
                if body["previous_hash"] != previous_hash:
                    raise RuntimeError(f"research run chain mismatch at line {line_number}")
                if record.get("record_hash") != expected:
                    raise RuntimeError(f"research run fingerprint mismatch at line {line_number}")
                if not isinstance(body["event"], dict) or not body["event"].get("id"):
                    raise RuntimeError(f"invalid research run event at line {line_number}")
                records.append(record)
                previous_hash = expected
        return records
