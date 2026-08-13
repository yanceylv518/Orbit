"""Run R0-DIAG2 on the frozen training period without opening the lockbox."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))
sys.path.insert(0, str(BACKEND_ROOT / "tools"))

from orbit.application.r0_direction_sequence_diagnostics import (  # noqa: E402
    create_direction_sequence_report,
)
from orbit.application.r0_path_diagnostics import assert_training_reproduced  # noqa: E402
from orbit.application.r0_shortline_screen import (  # noqa: E402
    training_report, validate_training_report, verify_frozen_context,
)
from orbit.domain.calibration.r0_shortline import (  # noqa: E402
    frozen_parameter_grid, simulate_symbol_events,
)
from screen_r0_shortline import (  # noqa: E402
    DEFAULT_ROOT, DEFAULT_SPEC, _market_loader, _prepare_universe, _write_exclusive,
)


DEFAULT_DIAG_SPEC = PROJECT_ROOT / "config" / "research" / "r0_direction_sequence_diagnostic.v1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--diag-spec", default=str(DEFAULT_DIAG_SPEC))
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--reproduction-checkpoint-dir")
    parser.add_argument("--reproduction-receipt")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    context = verify_frozen_context(Path(args.spec).resolve(), root)
    baseline_path = Path(args.baseline).resolve()
    baseline_bytes = baseline_path.read_bytes().replace(b"\r\n", b"\n")
    baseline_sha = hashlib.sha256(baseline_bytes).hexdigest()
    baseline = json.loads(baseline_bytes.decode("utf-8"))
    validate_training_report(context, baseline)
    diag = json.loads(Path(args.diag_spec).resolve().read_text(encoding="utf-8"))
    _validate_contract(diag, context, baseline, baseline_sha)

    end_ms = int(context["contract"]["sample_split"]["training_end_ms"])
    symbols, resolver = _prepare_universe(root, context["contract"], maximum_time_ms=end_ms)
    loader = _market_loader(root, minimum_time_ms=None, maximum_time_ms=end_ms)
    checkpoint_dir = Path(args.reproduction_checkpoint_dir).resolve() if args.reproduction_checkpoint_dir else None
    receipt_path = Path(args.reproduction_receipt).resolve() if args.reproduction_receipt else None
    checkpoint_sha = _checkpoint_set_sha256(checkpoint_dir, symbols) if checkpoint_dir else None
    if not _valid_reproduction_receipt(
        receipt_path, context["contract_sha256"], baseline_sha, checkpoint_sha,
    ):
        reproduced = training_report(
            context, symbols, loader, tier_at=resolver.tier_at,
            diagnostics_at=resolver.diagnostics_at, checkpoint_dir=checkpoint_dir,
        )
        assert_training_reproduced(baseline, reproduced)
        if receipt_path:
            _write_exclusive(receipt_path, {
                "protocol": "ORBIT_R0_DIAG2_REPRODUCTION_RECEIPT_V1",
                "contract_sha256": context["contract_sha256"],
                "baseline_report_sha256": baseline_sha,
                "checkpoint_set_sha256": checkpoint_sha,
                "training_report_exact_match": True,
                "verdict": reproduced["verdict"],
            })

    contract = context["contract"]
    costs = {str(item["tier"]): float(item["round_trip"]) for item in contract["execution"]["costs_pct_per_side_by_tier"]}
    grid = frozen_parameter_grid(contract)
    parameter_ids = [row["parameter_id"] for row in baseline["parameter_reports"]]
    if checkpoint_dir is not None:
        events_by_parameter = _events_from_reproduced_checkpoints(
            checkpoint_dir, symbols, parameter_ids, context["contract_sha256"],
        )
    else:
        events_by_parameter = {parameter_id: [] for parameter_id in parameter_ids}
        grid_by_id = {
            next(row["parameter_id"] for row in baseline["parameter_reports"] if row["definition_id"] == item["definition_id"] and row["parameters"] == item["parameters"]): item
            for item in grid
        }
        for symbol in sorted(symbols):
            candles, funding = loader(symbol)
            for parameter_id in parameter_ids:
                item = grid_by_id[parameter_id]
                events_by_parameter[parameter_id].extend(simulate_symbol_events(
                    symbol, candles, funding, item["definition_id"], item["parameters"],
                    tier_at=resolver.tier_at, diagnostics_at=resolver.diagnostics_at,
                    evaluation_start_ms=0, evaluation_end_ms=end_ms,
                    round_trip_cost_pct_by_tier=costs,
                ))

    statistics = contract["statistics"]
    report = create_direction_sequence_report(
        context, baseline, events_by_parameter,
        baseline_report_sha256=baseline_sha,
        bootstrap_samples=int(statistics["bootstrap_samples"]),
        bootstrap_seed=int(statistics["bootstrap_seed"]),
    )
    _write_exclusive(Path(args.out).resolve(), report)
    focus = report["family_reports"]["BREAKOUT_MOMENTUM"]["slices"]
    print(json.dumps({
        "verdict": baseline["verdict"], "diagnostic_report": str(Path(args.out).resolve()),
        "short_seq_4_plus": focus["direction_by_same_direction_sequence"]["SHORT"]["SEQ_4_PLUS"],
        "lockbox_opened": False,
    }, ensure_ascii=False))


def _validate_contract(diag, context, baseline, baseline_sha):
    if (
        diag.get("protocol") != "ORBIT_R0_DIRECTION_SEQUENCE_DIAGNOSTIC_CONTRACT_V1"
        or diag.get("status") != "FROZEN_AFTER_TRAINING_BEFORE_DIAGNOSTIC_MEASUREMENT"
        or diag.get("base_contract_sha256") != context["contract_sha256"]
        or diag.get("base_training_report_git_sha256") != baseline_sha
        or diag.get("base_verdict_required") != baseline.get("verdict")
        or diag.get("lockbox_access") != "PROHIBITED"
        or diag.get("selection_or_gate_effect") != "NONE"
        or diag.get("coverage") != "ALL_16_FROZEN_PARAMETER_COMBINATIONS"
    ):
        raise ValueError("R0-DIAG2 frozen contract does not match the baseline")


def _events_from_reproduced_checkpoints(directory, symbols, parameter_ids, contract_sha):
    result = {parameter_id: [] for parameter_id in parameter_ids}
    identity = f"{contract_sha}:TRAINING"
    for symbol in sorted(symbols):
        payload = json.loads((directory / f"{symbol}.json").read_text(encoding="utf-8"))
        if (
            payload.get("identity") != identity
            or payload.get("symbol") != symbol
            or payload.get("parameter_ids") != parameter_ids
            or len(payload.get("event_sets") or []) != len(parameter_ids)
        ):
            raise ValueError(f"R0-DIAG2 reproduction checkpoint mismatch: {symbol}")
        for parameter_id, events in zip(parameter_ids, payload["event_sets"]):
            result[parameter_id].extend(events)
    return result


def _checkpoint_set_sha256(directory, symbols):
    digest = hashlib.sha256()
    for symbol in sorted(symbols):
        path = directory / f"{symbol}.json"
        digest.update(symbol.encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _valid_reproduction_receipt(path, contract_sha, baseline_sha, checkpoint_sha):
    if path is None or not path.exists():
        return False
    receipt = json.loads(path.read_text(encoding="utf-8"))
    return (
        receipt.get("protocol") == "ORBIT_R0_DIAG2_REPRODUCTION_RECEIPT_V1"
        and receipt.get("contract_sha256") == contract_sha
        and receipt.get("baseline_report_sha256") == baseline_sha
        and receipt.get("checkpoint_set_sha256") == checkpoint_sha
        and receipt.get("training_report_exact_match") is True
        and receipt.get("verdict") == "TRAINING_FAIL"
    )


if __name__ == "__main__":
    main()
