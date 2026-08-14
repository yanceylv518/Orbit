from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any


GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class AppendOnlySignalLedger:
    """SIG-1 immutable manifest and append-only JSONL SHA-256 chain."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.manifest_path = directory / "manifest.json"
        self.events_path = directory / "events.jsonl"
        self._lock = threading.RLock()
        self._tail_sequence: int | None = None
        self._tail_hash: str | None = None

    def open(self, manifest: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            expected = dict(manifest)
            expected_hash = hashlib.sha256(canonical_json(expected)).hexdigest()
            if self.manifest_path.exists():
                stored = json.loads(self.manifest_path.read_text(encoding="utf-8"))
                stored_hash = stored.pop("manifest_sha256", None)
                if stored_hash != hashlib.sha256(canonical_json(stored)).hexdigest():
                    raise RuntimeError("SIG-1 manifest fingerprint mismatch")
                if stored != expected or stored_hash != expected_hash:
                    raise RuntimeError("SIG-1 immutable manifest differs from requested configuration")
                self.read_all()
                return stored | {"manifest_sha256": stored_hash}
            payload = expected | {"manifest_sha256": expected_hash}
            with self.manifest_path.open("x", encoding="utf-8", newline="\n") as target:
                json.dump(payload, target, ensure_ascii=False, sort_keys=True, indent=2)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            return payload

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.append_many([payload])[0]

    def append_many(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not payloads:
            return []
        with self._lock:
            if self._tail_sequence is None or self._tail_hash is None:
                self.read_all()
            sequence = int(self._tail_sequence or 0)
            previous_hash = self._tail_hash or GENESIS_HASH
            appended = []
            for payload in payloads:
                sequence += 1
                body = {
                    "sequence": sequence,
                    "previous_hash": previous_hash,
                    "payload": payload,
                }
                record_hash = hashlib.sha256(canonical_json(body)).hexdigest()
                appended.append(body | {"record_hash": record_hash})
                previous_hash = record_hash
            with self.events_path.open("a", encoding="utf-8", newline="\n") as target:
                for record in appended:
                    target.write(canonical_json(record).decode("utf-8") + "\n")
                target.flush()
                os.fsync(target.fileno())
            self._tail_sequence = sequence
            self._tail_hash = previous_hash
            return appended

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
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
                        raise RuntimeError(f"SIG-1 ledger sequence mismatch at line {line_number}")
                    if body["previous_hash"] != previous_hash:
                        raise RuntimeError(f"SIG-1 ledger chain mismatch at line {line_number}")
                    if record.get("record_hash") != expected:
                        raise RuntimeError(f"SIG-1 ledger fingerprint mismatch at line {line_number}")
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
