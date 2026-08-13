"""Run R0-DIAG against the frozen training period without opening the lockbox."""

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

from orbit.application.r0_path_diagnostics import (  # noqa: E402
    assert_training_reproduced,
    create_path_diagnostic_report,
    write_path_diagnostic_svgs,
)
from orbit.application.r0_shortline_screen import (  # noqa: E402
    training_report,
    validate_training_report,
    verify_frozen_context,
)
from screen_r0_shortline import (  # noqa: E402
    DEFAULT_ROOT,
    DEFAULT_SPEC,
    _market_loader,
    _prepare_universe,
    _write_exclusive,
)


DEFAULT_DIAG_SPEC = PROJECT_ROOT / "config" / "research" / "r0_path_diagnostic.v2.1.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    parser.add_argument("--diag-spec", default=str(DEFAULT_DIAG_SPEC))
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--chart-dir", required=True)
    parser.add_argument("--reproduction-checkpoint-dir")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    base_spec = Path(args.spec).resolve()
    diag_spec_path = Path(args.diag_spec).resolve()
    baseline_path = Path(args.baseline).resolve()
    output_path = Path(args.out).resolve()
    chart_dir = Path(args.chart_dir).resolve()

    context = verify_frozen_context(base_spec, root)
    diag_spec = json.loads(diag_spec_path.read_text(encoding="utf-8"))
    baseline_bytes = baseline_path.read_bytes()
    canonical_baseline_bytes = baseline_bytes.replace(b"\r\n", b"\n")
    baseline_sha = hashlib.sha256(canonical_baseline_bytes).hexdigest()
    baseline = json.loads(baseline_bytes.decode("utf-8"))
    validate_training_report(context, baseline)
    _validate_diag_contract(diag_spec, context, baseline, baseline_sha)

    training_end_ms = int(context["contract"]["sample_split"]["training_end_ms"])
    symbols, resolver = _prepare_universe(root, context["contract"], maximum_time_ms=training_end_ms)
    loader = _market_loader(root, minimum_time_ms=None, maximum_time_ms=training_end_ms)
    reproduced = training_report(
        context,
        symbols,
        loader,
        tier_at=resolver.tier_at,
        diagnostics_at=resolver.diagnostics_at,
        checkpoint_dir=(
            Path(args.reproduction_checkpoint_dir).resolve()
            if args.reproduction_checkpoint_dir else None
        ),
    )
    assert_training_reproduced(baseline, reproduced)
    report = create_path_diagnostic_report(
        context,
        baseline,
        symbols,
        loader,
        tier_at=resolver.tier_at,
        diagnostics_at=resolver.diagnostics_at,
        baseline_report_sha256=baseline_sha,
        focus_parameter_ids=diag_spec["focus"]["required_parameter_ids"],
    )
    _write_exclusive(output_path, report)
    charts = write_path_diagnostic_svgs(report, chart_dir)
    print(json.dumps({
        "verdict": baseline["verdict"],
        "diagnostic_report": str(output_path),
        "charts": charts,
        "lockbox_opened": False,
    }, ensure_ascii=False))


def _validate_diag_contract(diag, context, baseline, baseline_sha):
    if (
        diag.get("protocol") != "ORBIT_R0_PATH_DIAGNOSTIC_CONTRACT_V2_1"
        or diag.get("status") != "FROZEN_AFTER_TRAINING_BEFORE_DIAGNOSTIC_MEASUREMENT"
        or diag.get("base_contract_sha256") != context["contract_sha256"]
        or diag.get("base_training_report_git_sha256") != baseline_sha
        or diag.get("base_verdict_required") != baseline.get("verdict")
        or diag.get("lockbox_access") != "PROHIBITED"
        or diag.get("selection_or_gate_effect") != "NONE"
    ):
        raise ValueError("R0-DIAG frozen contract does not match the baseline")


if __name__ == "__main__":
    main()
