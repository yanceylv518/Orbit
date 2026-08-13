"""Run RB-1 training steps 1 and 2; this tool deliberately has no lockbox command."""

from __future__ import annotations

import argparse
import atexit
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.rb1_oversold import create_step1_report, create_step2_report, verify_context  # noqa: E402
from orbit.infrastructure.persistence.dataset_job_lock import DatasetJobLock  # noqa: E402
from screen_r0_shortline import _market_loader, _prepare_universe, _write_exclusive  # noqa: E402

DEFAULT_ROOT = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"
DEFAULT_SPEC = PROJECT_ROOT / "config" / "research" / "rb1_oversold.v1.json"
R0_SPEC = PROJECT_ROOT / "config" / "research" / "r0_shortline_screen.v2.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--spec", default=str(DEFAULT_SPEC))
    commands = parser.add_subparsers(dest="command", required=True)
    step1 = commands.add_parser("step1")
    step1.add_argument("--out", required=True)
    step1.add_argument("--checkpoint-dir", required=True)
    step2 = commands.add_parser("step2")
    step2.add_argument("--step1-report", required=True)
    step2.add_argument("--checkpoint-dir", required=True)
    step2.add_argument("--out", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    lock = DatasetJobLock(root, owner="rb1-cli", run_id=args.command)
    lock.acquire()
    atexit.register(lock.release)
    context = verify_context(Path(args.spec).resolve(), R0_SPEC, root)
    if args.command == "step1":
        end_ms = int(context["contract"]["sample_split"]["training_end_ms"])
        symbols, resolver = _prepare_universe(root, context["contract"], maximum_time_ms=end_ms)
        report = create_step1_report(
            context, symbols, _market_loader(root, minimum_time_ms=None, maximum_time_ms=end_ms),
            tier_at=resolver.tier_at, diagnostics_at=resolver.diagnostics_at,
            checkpoint_dir=Path(args.checkpoint_dir).resolve(),
        )
    else:
        step1_report = json.loads(Path(args.step1_report).read_text(encoding="utf-8"))
        report = create_step2_report(context, step1_report, Path(args.checkpoint_dir).resolve())
    _write_exclusive(Path(args.out), report)
    print(json.dumps({"phase": report["phase"], "verdict": report["verdict"], "output": str(Path(args.out).resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    main()
