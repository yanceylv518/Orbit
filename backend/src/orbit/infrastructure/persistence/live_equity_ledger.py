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
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


class AppendOnlyLiveEquityLedger:
    """Hash-chained LIVE-SMALL account-equity observations."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            records = self.read_all()
            if any(
                record["payload"].get("account_id") == payload.get("account_id")
                and record["payload"].get("synced_at_ms") == payload.get("synced_at_ms")
                for record in records
            ):
                return {"duplicate": True, "record": None}
            account_records = [
                record for record in records
                if record["payload"].get("account_id") == payload.get("account_id")
            ]
            if account_records and int(payload["synced_at_ms"]) < int(
                account_records[-1]["payload"]["synced_at_ms"]
            ):
                raise ValueError("live equity ledger cannot append an older account snapshot")
            previous_hash = records[-1]["record_hash"] if records else GENESIS_HASH
            body = {
                "sequence": len(records) + 1,
                "previous_hash": previous_hash,
                "payload": payload,
            }
            record = body | {
                "record_hash": hashlib.sha256(canonical_json(body)).hexdigest(),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as target:
                target.write(canonical_json(record).decode("utf-8") + "\n")
                target.flush()
                os.fsync(target.fileno())
            return {"duplicate": False, "record": record}

    def read_all(self) -> list[dict[str, Any]]:
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
                    "payload": record.get("payload"),
                }
                expected = hashlib.sha256(canonical_json(body)).hexdigest()
                if body["sequence"] != len(records) + 1:
                    raise RuntimeError(
                        f"live equity ledger sequence mismatch at line {line_number}"
                    )
                if body["previous_hash"] != previous_hash:
                    raise RuntimeError(
                        f"live equity ledger chain mismatch at line {line_number}"
                    )
                if record.get("record_hash") != expected:
                    raise RuntimeError(
                        f"live equity ledger fingerprint mismatch at line {line_number}"
                    )
                records.append(record)
                previous_hash = expected
        return records

    def observations(self, account_id: str) -> list[dict[str, Any]]:
        return [
            dict(record["payload"])
            for record in self.read_all()
            if record["payload"].get("account_id") == account_id
        ]

    def status(self) -> dict[str, Any]:
        records = self.read_all()
        return {
            "path": str(self.path),
            "event_count": len(records),
            "head_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
        }
