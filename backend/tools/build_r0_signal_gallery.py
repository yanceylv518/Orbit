"""Build the bounded R0-UI-2 gallery from frozen training checkpoints and raw candles."""

from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import defaultdict
import json
from pathlib import Path
import sys
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.r0_signal_gallery import canonical_sha256, deterministic_sample  # noqa: E402
from orbit.infrastructure.market_data.binance_public_archive import iter_kline_zip  # noqa: E402


DEFAULT_CONTRACT = PROJECT_ROOT / "config" / "research" / "r0_signal_gallery.v1.json"
DEFAULT_TRAINING = PROJECT_ROOT / "docs" / "evidence" / "r0" / "r0_training_v2_20260812.json"
DEFAULT_CHECKPOINTS = PROJECT_ROOT / "var" / "research" / "r0-diag-reproduction-checkpoints"
DEFAULT_DATA = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "evidence" / "r0" / "signal_gallery"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--training-report", default=str(DEFAULT_TRAINING))
    parser.add_argument("--checkpoints", default=str(DEFAULT_CHECKPOINTS))
    parser.add_argument("--data-root", default=str(DEFAULT_DATA))
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    contract_path = Path(args.contract).resolve()
    training_path = Path(args.training_report).resolve()
    checkpoints = Path(args.checkpoints).resolve()
    data_root = Path(args.data_root).resolve()
    output = Path(args.out).resolve()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    training = json.loads(training_path.read_text(encoding="utf-8"))
    _validate_inputs(contract, training_path, training, checkpoints)
    parameter_reports = training["parameter_reports"]
    ids = [str(item["parameter_id"]) for item in parameter_reports]
    events_by_id: list[list[dict[str, Any]]] = [[] for _ in ids]
    for path in sorted(checkpoints.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("parameter_ids") != ids:
            raise RuntimeError(f"checkpoint parameter order mismatch: {path.name}")
        for index, rows in enumerate(payload["event_sets"]):
            events_by_id[index].extend(rows)

    count = int(contract["sampling"]["per_stratum"])
    seed = int(contract["sampling"]["seed"])
    sampled_by_id = {
        parameter_id: deterministic_sample(events, parameter_id, seed=seed, count=count)
        for parameter_id, events in zip(ids, events_by_id)
    }
    needed_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for parameter_id, rows in sampled_by_id.items():
        for item in rows:
            needed_by_symbol[str(item["symbol"])].append({**item, "parameter_id": parameter_id})

    benchmark = _load_symbol(data_root, "BTCUSDT")
    projected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    before = int(contract["window"]["candles_before_signal"])
    multiple = int(contract["window"]["observation_holding_multiple"])
    for symbol, requested in sorted(needed_by_symbol.items()):
        candles = benchmark if symbol == "BTCUSDT" else _load_symbol(data_root, symbol)
        for event in requested:
            projected[event["parameter_id"]].append(
                project_event_window(event, candles, benchmark, before=before, multiple=multiple)
            )

    output.mkdir(parents=True, exist_ok=True)
    descriptors = []
    report_by_id = {str(item["parameter_id"]): item for item in parameter_reports}
    for parameter_id in ids:
        report = report_by_id[parameter_id]
        rows_by_id = {item["event_id"]: item for item in projected[parameter_id]}
        ordered_rows = [rows_by_id[item["event_id"]] for item in sampled_by_id[parameter_id]]
        payload = {
            "protocol": "ORBIT_R0_SIGNAL_GALLERY_PARAMETER_V1",
            "parameter_id": parameter_id,
            "family_id": report["family_id"],
            "definition_id": report["definition_id"],
            "parameters": report["parameters"],
            "population_event_count": int(report["summary"]["event_count"]),
            "samples": ordered_rows,
        }
        filename = f"{parameter_id.replace(':', '_')}.json"
        target = output / filename
        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        descriptors.append({
            "parameter_id": parameter_id,
            "family_id": report["family_id"],
            "definition_id": report["definition_id"],
            "parameters": report["parameters"],
            "population_event_count": int(report["summary"]["event_count"]),
            "sample_count": len(ordered_rows),
            "years": sorted({int(item["entry_year_utc"]) for item in ordered_rows}),
            "file": filename,
            "sha256": canonical_sha256(target),
        })
    manifest = {
        "protocol": "ORBIT_R0_SIGNAL_GALLERY_REPORT_V1",
        "gallery_contract_sha256": canonical_sha256(contract_path),
        "training_report_sha256": canonical_sha256(training_path),
        "dataset_fingerprint": contract["dataset_fingerprint"],
        "lockbox_opened": False,
        "parameter_reports": descriptors,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"parameters": len(descriptors), "samples": sum(x["sample_count"] for x in descriptors), "output": str(output)}, ensure_ascii=False))


def project_event_window(event, candles, benchmark, *, before, multiple):
    opens = [int(item.open_time_ms) for item in candles]
    entry_index = bisect_left(opens, int(event["entry_time_ms"]))
    if entry_index >= len(candles) or opens[entry_index] != int(event["entry_time_ms"]):
        raise RuntimeError(f"entry candle is absent: {event['symbol']} {event['entry_time_ms']}")
    holding = int(event["parameters"]["holding_candles"])
    start = max(0, entry_index - before - 1)
    end = entry_index + holding * multiple
    window = candles[start:end]
    if len(window) < holding * multiple:
        raise RuntimeError("gallery window crossed the frozen training boundary")
    compact = [_compact_candle(item) for item in window]
    benchmark_by_time = {int(item.open_time_ms): float(item.close) for item in benchmark}
    benchmark_values = [benchmark_by_time.get(int(item.open_time_ms)) for item in window]
    base = next((value for value in benchmark_values if value is not None), None)
    benchmark_line = [None if value is None or base is None else (value / base - 1) * 100 for value in benchmark_values]
    direction = 1 if event["direction"] == "LONG" else -1
    observed = candles[entry_index:end]
    favorable = [
        (float(item.high) - float(event["entry_price"])) * direction
        if direction > 0 else (float(event["entry_price"]) - float(item.low))
        for item in observed
    ]
    adverse = [
        float(event["entry_price"]) - float(item.low)
        if direction > 0 else float(item.high) - float(event["entry_price"])
        for item in observed
    ]
    mfe_index = max(range(len(observed)), key=lambda index: favorable[index])
    mae_index = max(range(len(observed)), key=lambda index: adverse[index])
    exit_index = next((index for index, item in enumerate(window) if int(item.open_time_ms) == int(event["exit_time_ms"])), None)
    stop_bar = exit_index - (entry_index - start) + 1 if exit_index is not None and str(event["exit_reason"]).startswith("STOP") else None
    executed_end = exit_index - (entry_index - start) if stop_bar else holding
    prior_mfe = max(favorable[:max(executed_end, 1)])
    recovered = bool(stop_bar and mfe_index + 1 > stop_bar and favorable[mfe_index] > prior_mfe + 1e-12)
    return {
        "event_id": event["event_id"], "sample_stratum": event["sample_stratum"],
        "symbol": event["symbol"], "direction": event["direction"], "tier": event["tier"],
        "volume_trend_3d": event["volume_trend_3d"], "listing_age": event["listing_age"],
        "signal_time_ms": event["signal_time_ms"], "entry_time_ms": event["entry_time_ms"],
        "exit_time_ms": event["exit_time_ms"], "entry_year_utc": event["entry_year_utc"],
        "entry_price": event["entry_price"], "stop_price": event["stop_price"],
        "exit_price": event["exit_price"], "exit_reason": event["exit_reason"],
        "net_return_pct": event["net_return_pct"], "holding_candles": holding,
        "stop_then_recovered_2h": recovered,
        "window": {"candles": compact, "benchmark_return_pct": benchmark_line},
        "annotations": {
            "signal_index": entry_index - start - 1, "entry_index": entry_index - start,
            "exit_index": exit_index, "post_exit_start_index": exit_index,
            "mfe_index": entry_index - start + mfe_index,
            "mae_index": entry_index - start + mae_index,
            "mfe_bar": mfe_index + 1, "mae_bar": mae_index + 1,
            "mfe_pct": max(favorable[mfe_index], 0) / float(event["entry_price"]) * 100,
            "mae_pct": max(adverse[mae_index], 0) / float(event["entry_price"]) * 100,
        },
    }


def _compact_candle(item):
    return [int(item.open_time_ms), float(item.open), float(item.high), float(item.low), float(item.close), float(item.quote_volume)]


def _load_symbol(root: Path, symbol: str):
    rows = []
    for path in sorted((root / "raw" / "klines" / "15m" / symbol).glob("*.zip")):
        for item in iter_kline_zip(path):
            if int(item.open_time_ms) <= 1735689599999:
                rows.append(item)
    if not rows:
        raise RuntimeError(f"no frozen candles for {symbol}")
    return rows


def _validate_inputs(contract, training_path, training, checkpoints):
    if (
        contract.get("protocol") != "ORBIT_R0_SIGNAL_GALLERY_V1"
        or contract.get("lockbox_access") != "PROHIBITED"
        or canonical_sha256(training_path) != contract.get("training_report_git_sha256")
        or training.get("contract_sha256") != contract.get("base_contract_sha256")
        or training.get("dataset_fingerprint") != contract.get("dataset_fingerprint")
        or not checkpoints.is_dir()
    ):
        raise RuntimeError("signal gallery inputs do not match the frozen training evidence")


if __name__ == "__main__":
    main()
