from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from orbit.application.r0_direction_sequence_diagnostics import annotate_same_direction_sequence
from orbit.application.r0_shortline_screen import verify_frozen_context as verify_r0_context
from orbit.domain.calibration.history import FundingPoint
from orbit.domain.calibration.r0_shortline import ShortlineCandle
from orbit.domain.calibration.rb1_oversold import (
    detect_signals, frozen_candidates, simulate_candidate_events, summarize_candidate,
)
from orbit.infrastructure.persistence.atomic_file import replace_with_retry

RB1_PROTOCOL = "ORBIT_RB1_OVERSOLD_V1"
RB1_CONTRACT_SHA256 = "af6148d886fdaf6eccd16bc3a67013f2fd47edd99004784d91f08a4c6995a494"


class RB1Error(RuntimeError):
    pass


def verify_context(spec_path: Path, r0_spec_path: Path, dataset_root: Path) -> dict[str, Any]:
    raw = spec_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != RB1_CONTRACT_SHA256:
        raise RB1Error("RB-1 machine contract fingerprint changed")
    contract = json.loads(raw.decode("utf-8"))
    if contract.get("protocol") != RB1_PROTOCOL or contract.get("status") != "FROZEN_BEFORE_TRAINING_EVALUATION":
        raise RB1Error("RB-1 machine contract is not frozen")
    if contract.get("discipline", {}).get("lockbox_access") != "PROHIBITED":
        raise RB1Error("RB-1 lockbox must remain prohibited for step 1/2")
    frozen_candidates(contract)
    r0 = verify_r0_context(r0_spec_path, dataset_root)
    if contract["inherits_from"]["contract_sha256"] != r0["contract_sha256"]:
        raise RB1Error("RB-1 inherited R-0 contract mismatch")
    expected = contract["dataset"]
    if (
        r0["manifest"]["dataset_fingerprint"] != expected["manifest_fingerprint"]
        or r0["manifest"]["quality_report_sha256"] != expected["quality_report_sha256"]
    ):
        raise RB1Error("RB-1 dataset identity mismatch")
    return {"contract": contract, "contract_sha256": actual, "manifest": r0["manifest"]}


def create_step1_report(
    context: Mapping[str, Any], symbols: Sequence[str],
    market_loader: Callable[[str], tuple[Sequence[ShortlineCandle], Sequence[FundingPoint]]], *,
    tier_at: Callable[[str, int], str | None],
    diagnostics_at: Callable[[str, int], Mapping[str, str] | None] | None = None,
    checkpoint_dir: Path | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    contract = context["contract"]
    end_ms = int(contract["sample_split"]["training_end_ms"])
    candidates = frozen_candidates(contract)
    event_sets = {item["id"]: [] for item in candidates}
    costs = {str(item["tier"]): float(item["round_trip"]) for item in contract["execution"]["costs_pct_per_side_by_tier"]}
    identity = f"{context['contract_sha256']}:STEP1"
    if checkpoint_dir:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for number, symbol in enumerate(sorted(symbols), 1):
        payload = _symbol_payload(
            symbol, identity, market_loader, tier_at, diagnostics_at, costs, end_ms,
            checkpoint_dir,
        )
        for candidate_id in event_sets:
            event_sets[candidate_id].extend(payload["events_by_candidate"][candidate_id])
        if progress_callback:
            progress_callback({"phase": "STEP1_SCAN", "completed_symbols": number, "total_symbols": len(symbols), "current_symbol": symbol})
    samples, seed = int(contract["statistics"]["bootstrap_samples"]), int(contract["statistics"]["bootstrap_seed"])
    reports = []
    for item in candidates:
        summary = summarize_candidate(event_sets[item["id"]], samples, seed)
        reports.append({"candidate_id": item["id"], "stop": item["stop"], "exit": item["exit"], "summary": summary})
    ranked = sorted(reports, key=_ranking_key)
    return {
        "protocol": "ORBIT_RB1_STEP1_TRAINING_V1", "phase": "STEP1_TRAINING",
        "contract_sha256": context["contract_sha256"],
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "training_end_ms": end_ms, "lockbox_opened": False,
        "lockbox_data_read": False, "grid_size": len(reports),
        "candidate_reports": reports,
        "ranking": [item["candidate_id"] for item in ranked],
        "winner": ranked[0]["candidate_id"],
        "verdict": "STEP1_WINNER_SELECTED_STEP2_PENDING",
    }


def create_step2_report(context: Mapping[str, Any], step1: Mapping[str, Any], checkpoint_dir: Path) -> dict[str, Any]:
    validate_step1(context, step1)
    winner = str(step1["winner"])
    events = []
    identity = f"{context['contract_sha256']}:STEP1"
    for path in sorted(checkpoint_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("identity") != identity:
            raise RB1Error("RB-1 checkpoint identity mismatch")
        events.extend(payload["events_by_candidate"][winner])
    expected = next(item for item in step1["candidate_reports"] if item["candidate_id"] == winner)
    if len(events) != int(expected["summary"]["event_count"]):
        raise RB1Error("RB-1 step2 checkpoints are incomplete")
    annotated = annotate_same_direction_sequence(events, maximum_gap_candles=96)
    selected = [item for item in annotated if int(item["same_direction_sequence_number"]) >= 3]
    stats = context["contract"]["statistics"]
    samples, seed = int(stats["bootstrap_samples"]), int(stats["bootstrap_seed"])
    all_summary = summarize_candidate(annotated, samples, seed)
    sequence_summary = summarize_candidate(selected, samples, seed)
    include = (
        float(sequence_summary["mean_net_return_pct"]) > float(all_summary["mean_net_return_pct"])
        and float(sequence_summary["bootstrap_mean_ci_low"]) > float(all_summary["bootstrap_mean_ci_low"])
    )
    return {
        "protocol": "ORBIT_RB1_STEP2_SEQUENCE_FILTER_V1", "phase": "STEP2_SEQUENCE_FILTER",
        "contract_sha256": context["contract_sha256"],
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "step1_winner": winner, "lockbox_opened": False, "lockbox_data_read": False,
        "sequence_definition": {"scope": "PER_SYMBOL", "maximum_gap_candles_inclusive": 96, "opposite_direction_resets": True, "uses_future_signals": False},
        "all_signals": all_summary, "seq_3_plus": sequence_summary,
        "filter_included": include,
        "final_signal_definition": "S1_DROP_STABILIZATION_SEQ_3_PLUS" if include else "S1_DROP_STABILIZATION_ALL",
        "verdict": "STEP2_COMPLETE_FREEZE_COMMIT_REQUIRED_BEFORE_LOCKBOX",
    }


def validate_step1(context: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    if report.get("protocol") != "ORBIT_RB1_STEP1_TRAINING_V1" or report.get("contract_sha256") != context["contract_sha256"]:
        raise RB1Error("invalid RB-1 step1 report")
    if report.get("lockbox_opened") or report.get("lockbox_data_read") or int(report.get("grid_size", 0)) != 4:
        raise RB1Error("RB-1 step1 discipline mismatch")
    ranked = sorted(report["candidate_reports"], key=_ranking_key)
    if report.get("winner") != ranked[0]["candidate_id"]:
        raise RB1Error("RB-1 winner does not match frozen ranking")


def _symbol_payload(symbol, identity, loader, tier_at, diagnostics_at, costs, end_ms, checkpoint_dir):
    path = checkpoint_dir / f"{symbol}.json" if checkpoint_dir else None
    if path and path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("identity") != identity or payload.get("symbol") != symbol:
            raise RB1Error("RB-1 checkpoint mismatch")
        return payload
    candles, funding = loader(symbol)
    signals = detect_signals(candles, start_ms=0, end_ms=end_ms)
    payload = {"protocol": "ORBIT_RB1_SYMBOL_CHECKPOINT_V1", "identity": identity, "symbol": symbol, "signal_count": len(signals), "events_by_candidate": {}}
    for candidate_id in ("ST-A__EX-A", "ST-A__EX-B", "ST-B__EX-A", "ST-B__EX-B"):
        payload["events_by_candidate"][candidate_id] = simulate_candidate_events(
            symbol, candles, funding, signals, candidate_id, tier_at=tier_at,
            costs=costs, end_ms=end_ms, diagnostics_at=diagnostics_at,
        )
    if path:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        replace_with_retry(temporary, path)
    return payload


def _ranking_key(item: Mapping[str, Any]):
    summary = item["summary"]
    return (-float(summary["bootstrap_mean_ci_low"]), -float(summary["mean_net_return_pct"]), -float(summary["worst_calendar_year_mean_net_return_pct"]), -int(summary["event_count"]), str(item["candidate_id"]))
