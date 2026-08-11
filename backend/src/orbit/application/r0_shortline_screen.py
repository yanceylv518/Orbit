from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from orbit.domain.calibration.history import FundingPoint
from orbit.domain.calibration.r0_shortline import (
    ShortlineCandle,
    apply_gates,
    frozen_parameter_grid,
    select_training_candidates,
    simulate_symbol_events,
    summarize_events,
)
from orbit.infrastructure.persistence.atomic_file import replace_with_retry


R0_CONTRACT_SHA256 = "a9a7abd45a69fd96e492549de2617a8ce472dce7cf56a80653060ed2f78a9799"
R0_PROTOCOL = "ORBIT_R0_SHORTLINE_SCREEN_V2"


class R0ScreenError(RuntimeError):
    pass


def verify_frozen_context(spec_path: Path, dataset_root: Path) -> dict[str, Any]:
    """Validate the frozen protocol and dataset identity before any market read."""
    raw = spec_path.read_bytes()
    actual_contract_sha = hashlib.sha256(raw).hexdigest()
    if actual_contract_sha != R0_CONTRACT_SHA256:
        raise R0ScreenError("R-0 machine contract fingerprint changed")
    contract = json.loads(raw.decode("utf-8"))
    if (
        contract.get("protocol") != R0_PROTOCOL
        or contract.get("status") != "FROZEN_BEFORE_SIGNAL_EVALUATION"
    ):
        raise R0ScreenError("R-0 machine contract is not frozen")

    manifest_path = dataset_root / "manifest.json"
    quality_path = dataset_root / "quality_report.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = contract["dataset"]
    manifest_entries_hash = _payload_hash(manifest.get("entries") or [])
    mismatches = []
    comparisons = {
        "protocol": (manifest.get("protocol"), expected["protocol"]),
        "dataset_fingerprint": (
            manifest.get("dataset_fingerprint"), expected["manifest_fingerprint"],
        ),
        "manifest_entries_hash": (
            manifest_entries_hash, expected["manifest_fingerprint"],
        ),
        "quality_report_sha256": (
            manifest.get("quality_report_sha256"), expected["quality_report_sha256"],
        ),
        "dataset_cutoff_ms": (
            manifest.get("dataset_cutoff_ms"), expected["dataset_cutoff_ms"],
        ),
        "raw_interval": (manifest.get("raw_interval"), expected["raw_interval"]),
        "dataset_state": (manifest.get("dataset_state"), expected["required_state"]),
    }
    for name, (actual, wanted) in comparisons.items():
        if actual != wanted:
            mismatches.append(name)
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality_core = {key: value for key, value in quality.items() if key != "report_sha256"}
    if (
        quality.get("report_sha256") != expected["quality_report_sha256"]
        or _payload_hash(quality_core) != expected["quality_report_sha256"]
    ):
        mismatches.append("quality_report_content")
    summary = quality.get("summary") or {}
    if int(summary.get("unverified_missing_15m_candles", -1)) != int(
        expected["required_unverified_missing_15m_candles"]
    ):
        mismatches.append("unverified_missing_15m_candles")
    if int(summary.get("duplicate_15m_candles", -1)) != int(
        expected["required_duplicate_15m_candles"]
    ):
        mismatches.append("duplicate_15m_candles")
    if mismatches:
        raise R0ScreenError("R-0 dataset contract mismatch: " + ", ".join(sorted(set(mismatches))))
    return {
        "contract": contract,
        "contract_sha256": actual_contract_sha,
        "manifest": manifest,
        "quality_report": quality,
    }


def evaluate_grid(
    contract: Mapping[str, Any],
    symbols: Sequence[str],
    market_loader: Callable[[str], tuple[Sequence[ShortlineCandle], Sequence[FundingPoint]]],
    *,
    tier_at: Callable[[str, int], str | None],
    evaluation_start_ms: int,
    evaluation_end_ms: int,
    gates: Mapping[str, Any],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None = None,
    selected_grid: Sequence[Mapping[str, Any]] | None = None,
    bootstrap_samples: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
    checkpoint_identity: str | None = None,
) -> list[dict[str, Any]]:
    if contract.get("diagnostics", {}).get("required_summary_dimensions") and diagnostics_at is None:
        raise R0ScreenError("R-0 V2 diagnostic resolver is required")
    grid = list(selected_grid or frozen_parameter_grid(contract))
    event_sets: list[list[dict[str, Any]]] = [[] for _ in grid]
    costs = {
        str(item["tier"]): float(item["round_trip"])
        for item in contract["execution"]["costs_pct_per_side_by_tier"]
    }
    ordered_symbols = sorted(symbols)
    parameter_ids = [_parameter_id(item) for item in grid]
    if checkpoint_dir is not None:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for symbol_index, symbol in enumerate(ordered_symbols, 1):
        generated_sets = _symbol_event_sets(
            contract,
            symbol,
            grid,
            parameter_ids,
            market_loader,
            tier_at=tier_at,
            diagnostics_at=diagnostics_at,
            evaluation_start_ms=evaluation_start_ms,
            evaluation_end_ms=evaluation_end_ms,
            costs=costs,
            checkpoint_dir=checkpoint_dir,
            checkpoint_identity=checkpoint_identity,
        )
        for index, generated in enumerate(generated_sets):
            event_sets[index].extend(generated)
        if progress_callback:
            progress_callback({
                "phase": "scan",
                "completed_symbols": symbol_index,
                "total_symbols": len(ordered_symbols),
                "current_symbol": symbol,
                "events_found": sum(len(events) for events in event_sets),
                "completed_combinations": 0,
                "total_combinations": len(grid),
            })
    statistics_contract = contract["statistics"]
    samples = int(bootstrap_samples or statistics_contract["bootstrap_samples"])
    seed = int(statistics_contract["bootstrap_seed"])
    reports = []
    for combination_index, (item, events) in enumerate(zip(grid, event_sets), 1):
        summary = summarize_events(events, bootstrap_samples=samples, bootstrap_seed=seed)
        parameter_report = {
            **item,
            "parameter_id": _parameter_id(item),
            "summary": summary,
            "gate": apply_gates(summary, gates),
        }
        reports.append(parameter_report)
        if progress_callback:
            progress_callback({
                "phase": "evaluate",
                "completed_symbols": len(ordered_symbols),
                "total_symbols": len(ordered_symbols),
                "current_symbol": None,
                "events_found": sum(len(events) for events in event_sets),
                "completed_combinations": combination_index,
                "total_combinations": len(grid),
                "current_combination": parameter_report["parameter_id"],
                "latest_parameter_report": parameter_report,
            })
    return reports


def training_report(
    context: Mapping[str, Any],
    symbols: Sequence[str],
    market_loader: Callable[[str], tuple[Sequence[ShortlineCandle], Sequence[FundingPoint]]],
    *,
    tier_at: Callable[[str, int], str | None],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None = None,
    bootstrap_samples: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    contract = context["contract"]
    split = contract["sample_split"]
    reports = evaluate_grid(
        contract, symbols, market_loader,
        tier_at=tier_at,
        diagnostics_at=diagnostics_at,
        evaluation_start_ms=0,
        evaluation_end_ms=int(split["training_end_ms"]),
        gates=contract["statistics"]["training_gates"],
        bootstrap_samples=bootstrap_samples,
        progress_callback=progress_callback,
        checkpoint_dir=checkpoint_dir,
        checkpoint_identity=f"{context['contract_sha256']}:TRAINING",
    )
    selected = select_training_candidates(reports)
    family_verdicts = {
        family: "TRAINING_PASS_LOCKBOX_PENDING" if report is not None else "TRAINING_FAIL"
        for family, report in selected.items()
    }
    return {
        "protocol": R0_PROTOCOL,
        "phase": "TRAINING",
        "contract_sha256": context["contract_sha256"],
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "quality_report_sha256": context["manifest"]["quality_report_sha256"],
        "parameter_reports": reports,
        "selected_candidates": {
            family: _compact_candidate(report) if report is not None else None
            for family, report in selected.items()
        },
        "family_verdicts": family_verdicts,
        "lockbox_authorized_families": [
            family for family, report in selected.items() if report is not None
        ],
        "verdict": (
            "TRAINING_PASS_LOCKBOX_PENDING"
            if any(report is not None for report in selected.values())
            else "TRAINING_FAIL"
        ),
    }


def lockbox_report(
    context: Mapping[str, Any],
    training: Mapping[str, Any],
    symbols: Sequence[str],
    market_loader: Callable[[str], tuple[Sequence[ShortlineCandle], Sequence[FundingPoint]]],
    *,
    tier_at: Callable[[str, int], str | None],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None = None,
    bootstrap_samples: int | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    checkpoint_dir: Path | None = None,
) -> dict[str, Any]:
    validate_training_report(context, training)
    selected = [
        item for item in training["selected_candidates"].values() if item is not None
    ]
    if not selected:
        raise R0ScreenError("training failed; lockbox data must not be read")
    contract = context["contract"]
    split = contract["sample_split"]
    reports = evaluate_grid(
        contract, symbols, market_loader,
        tier_at=tier_at,
        diagnostics_at=diagnostics_at,
        evaluation_start_ms=int(split["lockbox_start_ms"]),
        evaluation_end_ms=int(split["lockbox_end_ms"]),
        gates=contract["statistics"]["lockbox_gates"],
        selected_grid=selected,
        bootstrap_samples=bootstrap_samples,
        progress_callback=progress_callback,
        checkpoint_dir=checkpoint_dir,
        checkpoint_identity=f"{context['contract_sha256']}:LOCKBOX",
    )
    by_family = {item["family_id"]: item for item in reports}
    family_verdicts = {
        family: (
            "R0_FAMILY_PASS"
            if report is not None and by_family[family]["gate"]["passed"]
            else "LOCKBOX_FAIL" if report is not None else "TRAINING_FAIL"
        )
        for family, report in training["selected_candidates"].items()
    }
    overall = "R0_PASS" if "R0_FAMILY_PASS" in family_verdicts.values() else "R0_FAIL"
    return {
        "protocol": R0_PROTOCOL,
        "phase": "LOCKBOX",
        "contract_sha256": context["contract_sha256"],
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "parameter_reports": reports,
        "family_verdicts": family_verdicts,
        "verdict": overall,
        "authorization": (
            "UNLOCK_ARCHITECTURE_STAGE_2_RESEARCH_ONLY"
            if overall == "R0_PASS" else "FREEZE_SHORTLINE_PLATFORM_BUILD"
        ),
        "trading_authorized": False,
    }


def validate_training_report(context: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    if (
        report.get("protocol") != R0_PROTOCOL
        or report.get("phase") != "TRAINING"
        or report.get("contract_sha256") != context["contract_sha256"]
        or report.get("dataset_fingerprint") != context["manifest"]["dataset_fingerprint"]
    ):
        raise R0ScreenError("training report does not match frozen R-0 context")
    selected = select_training_candidates(report.get("parameter_reports") or [])
    expected = {
        family: _compact_candidate(item) if item is not None else None
        for family, item in selected.items()
    }
    if expected != report.get("selected_candidates"):
        raise R0ScreenError("training candidate selection was changed")


def _compact_candidate(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "family_id": report["family_id"],
        "definition_id": report["definition_id"],
        "parameters": report["parameters"],
        "parameter_id": report["parameter_id"],
    }


def _symbol_event_sets(
    contract: Mapping[str, Any],
    symbol: str,
    grid: Sequence[Mapping[str, Any]],
    parameter_ids: Sequence[str],
    market_loader: Callable[[str], tuple[Sequence[ShortlineCandle], Sequence[FundingPoint]]],
    *,
    tier_at: Callable[[str, int], str | None],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None,
    evaluation_start_ms: int,
    evaluation_end_ms: int,
    costs: Mapping[str, float],
    checkpoint_dir: Path | None,
    checkpoint_identity: str | None,
) -> list[list[dict[str, Any]]]:
    checkpoint = checkpoint_dir / f"{symbol}.json" if checkpoint_dir else None
    if checkpoint and checkpoint.exists():
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        if (
            payload.get("identity") != checkpoint_identity
            or payload.get("parameter_ids") != list(parameter_ids)
            or payload.get("symbol") != symbol
        ):
            raise R0ScreenError(f"R-0 checkpoint contract mismatch: {symbol}")
        event_sets = payload.get("event_sets")
        if not isinstance(event_sets, list) or len(event_sets) != len(grid):
            raise R0ScreenError(f"R-0 checkpoint is invalid: {symbol}")
        for events in event_sets:
            _validate_event_diagnostics(contract, events)
        return event_sets
    candles, funding = market_loader(symbol)
    result: list[list[dict[str, Any]]] = []
    for item in grid:
        generated = simulate_symbol_events(
            symbol,
            candles,
            funding,
            str(item["definition_id"]),
            item["parameters"],
            tier_at=tier_at,
            diagnostics_at=diagnostics_at,
            evaluation_start_ms=evaluation_start_ms,
            evaluation_end_ms=evaluation_end_ms,
            round_trip_cost_pct_by_tier=costs,
            atr_period=int(contract["execution"]["stop_atr_period"]),
            atr_multiple=float(contract["execution"]["stop_atr_multiple"]),
        )
        _validate_event_diagnostics(contract, generated)
        result.append(generated)
    if checkpoint:
        temporary = checkpoint.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "identity": checkpoint_identity,
            "symbol": symbol,
            "parameter_ids": list(parameter_ids),
            "event_sets": result,
        }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        replace_with_retry(temporary, checkpoint)
    return result


def _validate_event_diagnostics(
    contract: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
) -> None:
    diagnostics = contract.get("diagnostics") or {}
    definitions = {
        str(value["field"]): value
        for value in diagnostics.values()
        if isinstance(value, Mapping) and value.get("field")
    }
    for dimension in diagnostics.get("required_summary_dimensions") or []:
        definition = definitions.get(str(dimension)) or {}
        allowed = {str(item) for item in definition.get("groups") or []}
        if not allowed:
            raise R0ScreenError(f"R-0 V2 diagnostic contract is invalid: {dimension}")
        for event in events:
            if str(event.get(str(dimension), "")) not in allowed:
                raise R0ScreenError(
                    f"R-0 V2 event diagnostic is missing or invalid: {dimension}"
                )


def _parameter_id(item: Mapping[str, Any]) -> str:
    core = {
        "family_id": item["family_id"],
        "definition_id": item["definition_id"],
        "parameters": item["parameters"],
    }
    return f"{item['definition_id']}:{_payload_hash(core)[:12]}"


def _payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
