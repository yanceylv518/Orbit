"""Measure cost-adjusted counter-trend edge at fixed holding horizons."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import horizon_reversion_report  # noqa: E402
from orbit.domain.calibration.history import load_candles  # noqa: E402


def parse_dataset(value: str) -> tuple[str, Path]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("dataset must be NAME,PATH")
    return parts[0], Path(parts[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, type=parse_dataset)
    parser.add_argument("--horizon", action="append", required=True, type=int)
    parser.add_argument("--a-pct", type=float, default=1.5)
    parser.add_argument("--theta-pct", type=float, default=4.0)
    parser.add_argument("--cost-pct", type=float, default=0.14)
    parser.add_argument("--json-output")
    args = parser.parse_args()

    reports = []
    for name, path in args.dataset:
        closes = [candle.close for candle in load_candles(path)]
        for horizon in args.horizon:
            report = horizon_reversion_report(
                closes,
                args.a_pct,
                args.theta_pct,
                args.cost_pct,
                horizon,
            )
            reports.append({"market": name, "path": str(path), **report})
            print(
                f"{name} horizon={horizon} trades={report['trades']} "
                f"revert/extend/timeout={report['reversions']}/"
                f"{report['extensions']}/{report['timeouts']} "
                f"EV={report['expected_value_pct']:+.4f}% "
                f"net={report['net_return_pct']:+.3f}%"
            )

    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"reports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
