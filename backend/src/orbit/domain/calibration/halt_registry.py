from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any


HALT_REGISTRY_PROTOCOL = "ORBIT_DATA1R_HALT_REGISTRY_V1"
RAW_INTERVAL_MS = 15 * 60 * 1000
SYMBOL_RE = re.compile(r"^[A-Z0-9]+USDT$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HaltRegistryError(RuntimeError):
    pass


def load_halt_registry(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HaltRegistryError(f"cannot read halt registry: {path}") from exc
    if payload.get("protocol") != HALT_REGISTRY_PROTOCOL:
        raise HaltRegistryError("halt registry protocol is invalid")
    if payload.get("version") != 1 or not isinstance(payload.get("entries"), list):
        raise HaltRegistryError("halt registry version or entries are invalid")
    entries = [_validate_entry(item) for item in payload["entries"]]
    ids = [item["id"] for item in entries]
    keys = [_entry_key(item) for item in entries]
    if len(ids) != len(set(ids)) or len(keys) != len(set(keys)):
        raise HaltRegistryError("halt registry contains duplicate ids or windows")
    entries.sort(key=lambda item: (item["symbol"], item["month"], item["start_open_time_ms"]))
    core = {
        "protocol": HALT_REGISTRY_PROTOCOL,
        "version": 1,
        "entries": entries,
    }
    return {**core, "registry_sha256": _payload_hash(core)}


def entries_by_partition(registry: dict[str, Any]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in registry["entries"]:
        result.setdefault((entry["symbol"], entry["month"]), []).append(entry)
    return result


def window_key(item: dict[str, Any]) -> tuple[int, int, int]:
    return (
        int(item["start_open_time_ms"]),
        int(item["end_open_time_ms"]),
        int(item["count"]),
    )


def _validate_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise HaltRegistryError("halt registry entry must be an object")
    entry = dict(raw)
    required = {
        "id", "symbol", "month", "start_open_time_ms", "end_open_time_ms", "count",
        "classification", "archive_key", "archive_sha256", "checksum_url", "evidence_note",
    }
    missing = sorted(required - set(entry))
    if missing:
        raise HaltRegistryError(f"halt registry entry is missing: {', '.join(missing)}")
    symbol = str(entry["symbol"])
    month = str(entry["month"])
    start = int(entry["start_open_time_ms"])
    end = int(entry["end_open_time_ms"])
    count = int(entry["count"])
    expected_count = (end - start) // RAW_INTERVAL_MS + 1 if end >= start else 0
    if not SYMBOL_RE.fullmatch(symbol) or not MONTH_RE.fullmatch(month):
        raise HaltRegistryError(f"invalid halt registry market: {symbol}/{month}")
    if start % RAW_INTERVAL_MS or end % RAW_INTERVAL_MS or count != expected_count:
        raise HaltRegistryError(f"halt registry window is not an exact 15m range: {entry['id']}")
    expected_key = (
        f"data/futures/um/monthly/klines/{symbol}/15m/"
        f"{symbol}-15m-{month}.zip"
    )
    if entry["classification"] != "EXCHANGE_HALT" or entry["archive_key"] != expected_key:
        raise HaltRegistryError(f"invalid halt classification or archive key: {entry['id']}")
    archive_sha256 = str(entry["archive_sha256"])
    expected_checksum_url = f"https://data.binance.vision/{expected_key}.CHECKSUM"
    if not SHA256_RE.fullmatch(archive_sha256) or entry["checksum_url"] != expected_checksum_url:
        raise HaltRegistryError(f"invalid halt archive evidence: {entry['id']}")
    if not str(entry["evidence_note"]).strip():
        raise HaltRegistryError(f"halt registry evidence note is empty: {entry['id']}")
    return {
        "id": str(entry["id"]),
        "symbol": symbol,
        "month": month,
        "start_open_time_ms": start,
        "end_open_time_ms": end,
        "count": count,
        "classification": "EXCHANGE_HALT",
        "archive_key": expected_key,
        "archive_sha256": archive_sha256,
        "checksum_url": expected_checksum_url,
        "evidence_note": str(entry["evidence_note"]),
    }


def _entry_key(item: dict[str, Any]) -> tuple[str, str, int, int, int]:
    return (item["symbol"], item["month"], *window_key(item))


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
