from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any


GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


class TrendForwardLedger:
    """Append-only JSONL hash chain plus an immutable start manifest."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.manifest_path = directory / "manifest.json"
        self.events_path = directory / "events.jsonl"
        self._tail_sequence: int | None = None
        self._tail_hash: str | None = None

    def create_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = dict(manifest)
        payload["manifest_sha256"] = hashlib.sha256(canonical_json(manifest)).hexdigest()
        try:
            with self.manifest_path.open("x", encoding="utf-8", newline="\n") as target:
                json.dump(payload, target, ensure_ascii=False, sort_keys=True, indent=2)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
        except FileExistsError as exc:
            raise RuntimeError("TB4 forward manifest already exists and is immutable") from exc
        return payload

    def initialize(
        self,
        manifest: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if self.directory.exists():
            raise RuntimeError("TB4 forward directory already exists and cannot be overwritten")
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(
            prefix=f".{self.directory.name}-staging-",
            dir=self.directory.parent,
        ))
        try:
            staged = TrendForwardLedger(staging)
            payload = staged.create_manifest(manifest)
            staged.append_many(events)
            staging.replace(self.directory)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        self._tail_sequence = len(events)
        records = self.read_all()
        self._tail_hash = records[-1]["record_hash"] if records else GENESIS_HASH
        return payload

    def manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        digest = payload.pop("manifest_sha256", None)
        expected = hashlib.sha256(canonical_json(payload)).hexdigest()
        if digest != expected:
            raise RuntimeError("TB4 forward manifest fingerprint mismatch")
        return payload | {"manifest_sha256": digest}

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.append_many([payload])[0]

    def append_many(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payloads:
            return []
        if self._tail_sequence is None or self._tail_hash is None:
            records = self.read_all()
            self._tail_sequence = len(records)
            self._tail_hash = records[-1]["record_hash"] if records else GENESIS_HASH
        records = []
        sequence = self._tail_sequence
        previous_hash = self._tail_hash
        for payload in payloads:
            sequence += 1
            body = {
                "sequence": sequence,
                "previous_hash": previous_hash,
                "payload": payload,
            }
            record = body | {"record_hash": hashlib.sha256(canonical_json(body)).hexdigest()}
            records.append(record)
            previous_hash = record["record_hash"]
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as target:
            for record in records:
                target.write(canonical_json(record).decode("utf-8") + "\n")
            target.flush()
            os.fsync(target.fileno())
        self._tail_sequence = sequence
        self._tail_hash = previous_hash
        return records

    def read_all(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        records = []
        previous_hash = GENESIS_HASH
        with self.events_path.open("r", encoding="utf-8") as source:
            for line_number, raw in enumerate(source, start=1):
                if not raw.strip():
                    continue
                record = json.loads(raw)
                body = {
                    "sequence": record.get("sequence"),
                    "previous_hash": record.get("previous_hash"),
                    "payload": record.get("payload"),
                }
                expected = hashlib.sha256(canonical_json(body)).hexdigest()
                if body["sequence"] != len(records) + 1:
                    raise RuntimeError(f"TB4 ledger sequence mismatch at line {line_number}")
                if body["previous_hash"] != previous_hash:
                    raise RuntimeError(f"TB4 ledger chain mismatch at line {line_number}")
                if record.get("record_hash") != expected:
                    raise RuntimeError(f"TB4 ledger fingerprint mismatch at line {line_number}")
                records.append(record)
                previous_hash = expected
        self._tail_sequence = len(records)
        self._tail_hash = previous_hash
        return records

    def status(self) -> dict[str, Any]:
        records = self.read_all()
        return {
            "manifest_exists": self.manifest_path.exists(),
            "event_count": len(records),
            "head_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
        }
