from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from orbit.domain.calibration.r0_shortline import daily_block_bootstrap_interval


R0_DIAG2_PROTOCOL = "ORBIT_R0_DIRECTION_SEQUENCE_DIAGNOSTIC_V1"
SEQUENCE_BUCKETS = ("SEQ_1", "SEQ_2", "SEQ_3", "SEQ_4_PLUS")
DIRECTIONS = ("LONG", "SHORT")


def annotate_same_direction_sequence(
    events: Sequence[Mapping[str, Any]], *, maximum_gap_candles: int = 96,
    candle_interval_ms: int = 15 * 60 * 1000,
) -> list[dict[str, Any]]:
    """Label each event using only earlier signals for the same symbol.

    A direction change resets the current event to one. The inclusive 96-candle
    boundary is measured between signal timestamps, independently per symbol.
    """
    maximum_gap_ms = maximum_gap_candles * candle_interval_ms
    states: dict[str, tuple[str, int, int]] = {}
    annotated: list[dict[str, Any]] = []
    ordered = sorted(
        (dict(item) for item in events),
        key=lambda item: (int(item["signal_time_ms"]), str(item["symbol"])),
    )
    for event in ordered:
        symbol = str(event["symbol"])
        direction = str(event["direction"])
        signal_time = int(event["signal_time_ms"])
        prior = states.get(symbol)
        if (
            prior is None
            or prior[0] != direction
            or signal_time - prior[1] > maximum_gap_ms
        ):
            sequence_number = 1
        else:
            sequence_number = prior[2] + 1
        states[symbol] = (direction, signal_time, sequence_number)
        event["same_direction_sequence_number"] = sequence_number
        event["same_direction_sequence_bucket"] = sequence_bucket(sequence_number)
        annotated.append(event)
    return annotated


def sequence_bucket(number: int) -> str:
    if number < 1:
        raise ValueError("sequence number must be positive")
    return f"SEQ_{number}" if number < 4 else "SEQ_4_PLUS"


def summarize_direction_sequence_slices(
    events: Sequence[Mapping[str, Any]], *, bootstrap_samples: int, bootstrap_seed: int,
    include_intervals: bool = True,
) -> dict[str, Any]:
    rows = list(events)
    by_direction = {
        direction: _summary(
            [item for item in rows if item["direction"] == direction],
            bootstrap_samples, bootstrap_seed, include_intervals,
        )
        for direction in DIRECTIONS
    }
    by_sequence = {
        bucket: _summary(
            [item for item in rows if item["same_direction_sequence_bucket"] == bucket],
            bootstrap_samples, bootstrap_seed, include_intervals,
        )
        for bucket in SEQUENCE_BUCKETS
    }
    direction_by_sequence = {
        direction: {
            bucket: _summary([
                item for item in rows
                if item["direction"] == direction
                and item["same_direction_sequence_bucket"] == bucket
            ], bootstrap_samples, bootstrap_seed, False)
            for bucket in SEQUENCE_BUCKETS
        }
        for direction in DIRECTIONS
    }
    return {
        "overall": _summary(rows, bootstrap_samples, bootstrap_seed, include_intervals),
        "by_direction": by_direction,
        "by_same_direction_sequence": by_sequence,
        "direction_by_same_direction_sequence": direction_by_sequence,
    }


def create_direction_sequence_report(
    context: Mapping[str, Any], baseline_report: Mapping[str, Any],
    events_by_parameter: Mapping[str, Sequence[Mapping[str, Any]]], *,
    baseline_report_sha256: str, bootstrap_samples: int, bootstrap_seed: int,
) -> dict[str, Any]:
    baseline_by_id = {
        str(item["parameter_id"]): item
        for item in baseline_report.get("parameter_reports") or []
    }
    if set(events_by_parameter) != set(baseline_by_id):
        raise ValueError("R0-DIAG2 requires all frozen parameter combinations")

    parameter_reports = []
    family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    definition_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for parameter_id in sorted(baseline_by_id):
        baseline = baseline_by_id[parameter_id]
        events = annotate_same_direction_sequence(events_by_parameter[parameter_id])
        expected_count = int(baseline["summary"]["event_count"])
        actual_mean = _mean(events)
        expected_mean = float(baseline["summary"]["mean_net_return_pct"])
        if len(events) != expected_count or actual_mean is None or abs(actual_mean - expected_mean) > 1e-12:
            raise ValueError("R0-DIAG2 event reproduction differs from frozen training")
        if baseline["family_id"] == "OVERSOLD_REBOUND" and any(
            item["direction"] == "SHORT" for item in events
        ):
            raise ValueError("oversold family produced a forbidden SHORT event")
        family_rows[str(baseline["family_id"])].extend(events)
        definition_rows[str(baseline["definition_id"])].extend(events)
        parameter_reports.append({
            "parameter_id": parameter_id,
            "family_id": baseline["family_id"],
            "definition_id": baseline["definition_id"],
            "parameters": baseline["parameters"],
            "reproduction": {
                "event_count": len(events),
                "mean_net_return_pct": actual_mean,
                "matches_frozen_training": True,
            },
            "slices": summarize_direction_sequence_slices(
                events, bootstrap_samples=bootstrap_samples, bootstrap_seed=bootstrap_seed,
            ),
        })

    return {
        "protocol": R0_DIAG2_PROTOCOL,
        "purpose": "DIAGNOSE_DIRECTION_AND_REPEATED_SAME_DIRECTION_SIGNALS_ONLY",
        "contract_sha256": context["contract_sha256"],
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "baseline_report_sha256": baseline_report_sha256,
        "baseline_verdict": baseline_report.get("verdict"),
        "lockbox_opened": False,
        "selection_or_gate_effect": "NONE",
        "sequence_definition": {
            "scope": "PER_PARAMETER_PER_SYMBOL",
            "interval": "15m",
            "maximum_gap_candles_inclusive": 96,
            "opposite_direction_resets": True,
            "uses_future_signals": False,
        },
        "parameter_reports": parameter_reports,
        "definition_reports": {
            definition: {
                "aggregation_unit": "PARAMETER_EVENT_OBSERVATION",
                "slices": summarize_direction_sequence_slices(
                    events, bootstrap_samples=bootstrap_samples, bootstrap_seed=bootstrap_seed,
                ),
            }
            for definition, events in sorted(definition_rows.items())
        },
        "family_reports": {
            family: {
                "aggregation_unit": "PARAMETER_EVENT_OBSERVATION",
                "slices": summarize_direction_sequence_slices(
                    events, bootstrap_samples=bootstrap_samples, bootstrap_seed=bootstrap_seed,
                ),
            }
            for family, events in sorted(family_rows.items())
        },
    }


def _summary(
    events: Sequence[Mapping[str, Any]], samples: int, seed: int, include_interval: bool,
) -> dict[str, Any]:
    rows = list(events)
    if not rows:
        result = {"event_count": 0, "mean_net_return_pct": None}
        if include_interval:
            result.update({"bootstrap_mean_ci_low": None, "bootstrap_mean_ci_high": None})
        return result
    result = {"event_count": len(rows), "mean_net_return_pct": _mean(rows)}
    if not include_interval:
        return result
    low, high = daily_block_bootstrap_interval(rows, samples=samples, seed=seed)
    result.update({"bootstrap_mean_ci_low": low, "bootstrap_mean_ci_high": high})
    return result


def _mean(events: Sequence[Mapping[str, Any]]) -> float | None:
    values = [float(item["net_return_pct"]) for item in events]
    return sum(values) / len(values) if values else None
