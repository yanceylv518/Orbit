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


class AppendOnlyLiveExecutionLedger:
    """Hash-chained LIVE-SMALL execution/control events.

    A ROUND_STARTED or ROUND_REJECTED event durably consumes a rebalance id.
    This deliberately favors an incomplete round over duplicate live orders.
    """

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            records = self.read_all()
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
            return record

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            records: list[dict[str, Any]] = []
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
                            "live execution ledger sequence mismatch "
                            f"at line {line_number}"
                        )
                    if body["previous_hash"] != previous_hash:
                        raise RuntimeError(
                            f"live execution ledger chain mismatch at line {line_number}"
                        )
                    if record.get("record_hash") != expected:
                        raise RuntimeError(
                            "live execution ledger fingerprint mismatch "
                            f"at line {line_number}"
                        )
                    records.append(record)
                    previous_hash = expected
            return records

    def round_consumed(self, epoch: str, rebalance_time_ms: int) -> bool:
        return any(
            item["payload"].get("event_type") in {
                "ROUND_STARTED", "ROUND_REJECTED", "ROUND_COMPLETED",
            }
            and item["payload"].get("execution_epoch") == epoch
            and int(item["payload"].get("rebalance_time_ms") or 0)
            == int(rebalance_time_ms)
            for item in self.read_all()
        )

    def stopped(self, epoch: str) -> tuple[bool, str | None]:
        for item in reversed(self.read_all()):
            payload = item["payload"]
            if payload.get("execution_epoch") != epoch:
                continue
            if payload.get("event_type") in {
                "EMERGENCY_STOP", "PROTOCOL_STOP", "PROTOCOL_VIOLATION",
            }:
                return True, str(payload.get("reason") or payload["event_type"])
        return False, None

    def latest_report(self, epoch: str) -> dict[str, Any] | None:
        for item in reversed(self.read_all()):
            payload = item["payload"]
            if (
                payload.get("execution_epoch") == epoch
                and payload.get("event_type") == "ROUND_COMPLETED"
            ):
                return dict(payload.get("report") or {})
        return None

    def incomplete_round(self, epoch: str) -> int | None:
        records = self.read_all()
        completed = {
            int(item["payload"].get("rebalance_time_ms") or 0)
            for item in records
            if item["payload"].get("execution_epoch") == epoch
            and item["payload"].get("event_type") == "ROUND_COMPLETED"
        }
        for item in reversed(records):
            payload = item["payload"]
            rebalance = int(payload.get("rebalance_time_ms") or 0)
            if (
                payload.get("execution_epoch") == epoch
                and payload.get("event_type") == "ROUND_STARTED"
                and rebalance not in completed
            ):
                return rebalance
        return None

    def protocol_violation(self, epoch: str, allowed_symbols: set[str]) -> str | None:
        records = self.read_all()
        rounds: dict[int, dict[str, Any]] = {}
        for item in records:
            payload = item["payload"]
            if payload.get("execution_epoch") != epoch:
                continue
            if payload.get("event_type") == "ROUND_STARTED":
                rounds[int(payload.get("rebalance_time_ms") or 0)] = payload
        for item in records:
            payload = item["payload"]
            if payload.get("execution_epoch") != epoch:
                continue
            if payload.get("event_type") != "ORDER_RESULT":
                continue
            intent = payload.get("order_intent") or {}
            symbol = str(payload.get("symbol") or "")
            rebalance = int(payload.get("rebalance_time_ms") or 0)
            round_start = rounds.get(rebalance) or {}
            checklist_rows = round_start.get("checklist_rows") or {}
            if (
                symbol not in allowed_symbols
                or intent.get("source") != "FROZEN_TB4_CHECKLIST"
                or checklist_rows.get(symbol)
                != payload.get("checklist_row_sha256")
                or intent.get("checklist_sha256")
                != round_start.get("checklist_sha256")
            ):
                return f"unmapped live order record at sequence {item['sequence']}"
        return None

    def status(self) -> dict[str, Any]:
        records = self.read_all()
        return {
            "path": str(self.path),
            "event_count": len(records),
            "head_hash": records[-1]["record_hash"] if records else GENESIS_HASH,
        }
