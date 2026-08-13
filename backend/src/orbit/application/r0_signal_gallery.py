from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


class R0SignalGalleryError(RuntimeError):
    pass


def canonical_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def event_id(parameter_id: str, event: Mapping[str, Any]) -> str:
    identity = ":".join((
        parameter_id,
        str(event["symbol"]),
        str(event["entry_time_ms"]),
        str(event["exit_time_ms"]),
    ))
    return hashlib.sha256(identity.encode()).hexdigest()[:20]


def deterministic_sample(
    events: Sequence[Mapping[str, Any]], parameter_id: str, *, seed: int, count: int,
) -> list[dict[str, Any]]:
    """Freeze disjoint best/worst/random strata without loading market candles."""
    ordered = sorted(
        events,
        key=lambda item: (
            float(item["net_return_pct"]), str(item["symbol"]), int(item["entry_time_ms"]),
        ),
    )
    bottom = ordered[:count]
    top = list(reversed(ordered[-count:]))
    excluded = {event_id(parameter_id, item) for item in [*bottom, *top]}
    remainder = [item for item in ordered if event_id(parameter_id, item) not in excluded]
    random_order = sorted(
        remainder,
        key=lambda item: hashlib.sha256(
            f"{seed}:{parameter_id}:{event_id(parameter_id, item)}".encode()
        ).hexdigest(),
    )
    sampled = []
    for stratum, rows in (
        ("BOTTOM_NET_RETURN", bottom),
        ("TOP_NET_RETURN", top),
        ("DETERMINISTIC_RANDOM", random_order[:count]),
    ):
        for item in rows:
            sampled.append({**dict(item), "event_id": event_id(parameter_id, item), "sample_stratum": stratum})
    return sampled


class R0SignalGalleryStore:
    """Bounded read model: one manifest plus one parameter file per request."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.contract_path = project_root / "config" / "research" / "r0_signal_gallery.v1.json"
        self.gallery_root = project_root / "docs" / "evidence" / "r0" / "signal_gallery"
        self.manifest_path = self.gallery_root / "manifest.json"

    def catalog(self) -> dict[str, Any]:
        contract, manifest = self._validated_manifest()
        return {
            "protocol": manifest["protocol"],
            "discipline_notice": "看图产生假设，数据裁决假设；本页不能修改参数或重跑旧协议。",
            "lockbox_opened": False,
            "sampling": contract["sampling"],
            "window": contract["window"],
            "parameter_reports": manifest["parameter_reports"],
        }

    def samples(self, parameter_id: str, filters: Mapping[str, Any]) -> dict[str, Any]:
        contract, manifest = self._validated_manifest()
        descriptor = self._descriptor(manifest, parameter_id)
        payload = self._parameter_payload(descriptor, parameter_id, contract)
        rows = payload["samples"]
        cohort = str(filters.get("cohort") or "ALL")
        year = filters.get("year")
        tier = filters.get("tier")
        volume_trend = filters.get("volume_trend")
        listing_age = filters.get("listing_age")
        if cohort == "PROFITABLE":
            rows = [item for item in rows if float(item["net_return_pct"]) > 0]
        elif cohort == "UNPROFITABLE":
            rows = [item for item in rows if float(item["net_return_pct"]) <= 0]
        elif cohort == "STOP_THEN_RECOVERED":
            rows = [item for item in rows if item.get("stop_then_recovered_2h") is True]
        elif cohort != "ALL":
            raise R0SignalGalleryError("unsupported signal gallery cohort")
        if year is not None:
            rows = [item for item in rows if int(item["entry_year_utc"]) == int(year)]
        if tier:
            rows = [item for item in rows if item.get("tier") == tier]
        if volume_trend:
            rows = [item for item in rows if item.get("volume_trend_3d") == volume_trend]
        if listing_age:
            rows = [item for item in rows if item.get("listing_age") == listing_age]
        limit = min(max(int(filters.get("limit") or 24), 1), 24)
        return {
            "parameter_id": parameter_id,
            "family_id": payload["family_id"],
            "parameters": payload["parameters"],
            "total_sampled": len(payload["samples"]),
            "matching_count": len(rows),
            "items": rows[:limit],
            "lockbox_opened": False,
        }

    def event(self, parameter_id: str, requested_event_id: str) -> dict[str, Any]:
        contract, manifest = self._validated_manifest()
        descriptor = self._descriptor(manifest, parameter_id)
        payload = self._parameter_payload(descriptor, parameter_id, contract)
        item = next((row for row in payload["samples"] if row["event_id"] == requested_event_id), None)
        if item is None:
            raise KeyError(requested_event_id)
        return item

    def _validated_manifest(self):
        contract = self._read_dict(self.contract_path)
        manifest = self._read_dict(self.manifest_path)
        if (
            contract.get("protocol") != "ORBIT_R0_SIGNAL_GALLERY_V1"
            or contract.get("lockbox_access") != "PROHIBITED"
            or manifest.get("protocol") != "ORBIT_R0_SIGNAL_GALLERY_REPORT_V1"
            or manifest.get("gallery_contract_sha256") != canonical_sha256(self.contract_path)
            or manifest.get("dataset_fingerprint") != contract.get("dataset_fingerprint")
            or manifest.get("training_report_sha256") != contract.get("training_report_git_sha256")
            or manifest.get("lockbox_opened") is not False
        ):
            raise R0SignalGalleryError("signal gallery evidence does not match its frozen contract")
        return contract, manifest

    def _parameter_payload(self, descriptor, parameter_id, contract):
        path = self.gallery_root / descriptor["file"]
        if canonical_sha256(path) != descriptor["sha256"]:
            raise R0SignalGalleryError("signal gallery parameter evidence fingerprint mismatch")
        payload = self._read_dict(path)
        if payload.get("parameter_id") != parameter_id:
            raise R0SignalGalleryError("signal gallery parameter evidence identity mismatch")
        lockbox_start = int(contract["lockbox_start_ms"])
        if any(int(item["signal_time_ms"]) >= lockbox_start for item in payload.get("samples") or []):
            raise R0SignalGalleryError("signal gallery contains a prohibited lockbox event")
        return payload

    @staticmethod
    def _descriptor(manifest, parameter_id):
        item = next((row for row in manifest["parameter_reports"] if row["parameter_id"] == parameter_id), None)
        if item is None:
            raise KeyError(parameter_id)
        return item

    @staticmethod
    def _read_dict(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise R0SignalGalleryError(f"signal gallery evidence is unavailable: {path.name}") from exc
        if not isinstance(payload, dict):
            raise R0SignalGalleryError("signal gallery evidence must be an object")
        return payload
