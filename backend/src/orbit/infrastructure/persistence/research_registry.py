from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from orbit.application.research.candidates import canonical_json, freeze_candidate


GENESIS_HASH = "0" * 64


class AppendOnlyResearchRegistry:
    """Hash-chained candidate registry. Existing candidate IDs are immutable."""

    def __init__(self, path: Path):
        self.path = path

    def all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        candidates = []
        candidate_ids: set[str] = set()
        previous_hash = GENESIS_HASH
        with self.path.open("r", encoding="utf-8") as source:
            for line_number, raw in enumerate(source, start=1):
                if not raw.strip():
                    continue
                record = json.loads(raw)
                body = {
                    "sequence": record.get("sequence"),
                    "previous_hash": record.get("previous_hash"),
                    "candidate": record.get("candidate"),
                }
                expected = hashlib.sha256(canonical_json(body)).hexdigest()
                if body["sequence"] != len(candidates) + 1:
                    raise RuntimeError(f"research registry sequence mismatch at line {line_number}")
                if body["previous_hash"] != previous_hash:
                    raise RuntimeError(f"research registry chain mismatch at line {line_number}")
                if record.get("record_hash") != expected:
                    raise RuntimeError(f"research registry fingerprint mismatch at line {line_number}")
                candidate = freeze_candidate(body["candidate"])
                if candidate["frozen_hash"] != body["candidate"].get("frozen_hash"):
                    raise RuntimeError(f"research candidate frozen hash mismatch at line {line_number}")
                if candidate["id"] in candidate_ids:
                    raise RuntimeError(f"duplicate research candidate at line {line_number}")
                candidates.append(candidate)
                candidate_ids.add(candidate["id"])
                previous_hash = expected
        return candidates

    def append(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        frozen = freeze_candidate(candidate)
        existing = self.all()
        if any(item["id"] == frozen["id"] for item in existing):
            raise RuntimeError(f"research candidate {frozen['id']} is frozen and cannot be changed")
        previous_hash = self._head_hash() if existing else GENESIS_HASH
        body = {
            "sequence": len(existing) + 1,
            "previous_hash": previous_hash,
            "candidate": frozen,
        }
        record = body | {"record_hash": hashlib.sha256(canonical_json(body)).hexdigest()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as target:
            target.write(canonical_json(record).decode("utf-8") + "\n")
            target.flush()
            os.fsync(target.fileno())
        return frozen

    def ensure(self, candidates: tuple[Mapping[str, Any], ...]) -> None:
        existing = {item["id"]: item for item in self.all()}
        for candidate in candidates:
            frozen = freeze_candidate(candidate)
            current = existing.get(frozen["id"])
            if current and current["frozen_hash"] != frozen["frozen_hash"]:
                raise RuntimeError(f"seed candidate {frozen['id']} differs from its frozen registry record")
            if not current:
                self.append(frozen)
                existing[frozen["id"]] = frozen

    def replace(self, _candidate_id: str, _candidate: Mapping[str, Any]) -> None:
        raise RuntimeError("frozen research candidates cannot be replaced")

    def _head_hash(self) -> str:
        last = None
        with self.path.open("r", encoding="utf-8") as source:
            for raw in source:
                if raw.strip():
                    last = json.loads(raw)
        return str(last["record_hash"]) if last else GENESIS_HASH
