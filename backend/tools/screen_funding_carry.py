"""Screen an optimistic funding-only carry upper bound on non-overlapping windows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (  # noqa: E402
    funding_carry_return_summary,
    funding_carry_screen,
)
from orbit.domain.calibration.history import load_funding  # noqa: E402


WINDOWS = (3, 9, 21, 42, 90)


def parse_dataset(value: str) -> tuple[str, Path]:
    parts = value.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("dataset must be NAME,PATH")
    return parts[0], Path(parts[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, type=parse_dataset)
    parser.add_argument("--entry-exit-cost-pct", type=float, default=0.38)
    parser.add_argument("--rebalance-cost-pct-per-day", type=float, default=0.02)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20_260_713)
    parser.add_argument("--json-output")
    args = parser.parse_args()

    markets = []
    for name, path in args.dataset:
        points = load_funding(path)
        reports = {}
        for window in WINDOWS:
            report = funding_carry_screen(
                points,
                window,
                entry_exit_cost_pct=args.entry_exit_cost_pct,
                rebalance_cost_pct_per_day=args.rebalance_cost_pct_per_day,
                bootstrap_samples=args.bootstrap_samples,
                bootstrap_seed=args.bootstrap_seed,
            )
            reports[str(window)] = report
            print(
                f"{name} days={report['holding_days']:.0f} events={report['events']} "
                f"gross={report['mean_gross_funding_pct']:+.4f}% "
                f"net={report['mean_net_carry_pct']:+.4f}% "
                f"ci_low={report['bootstrap_mean_ci_low']:+.4f}% "
                f"stage={'PASS' if report['admitted'] else 'FAIL'}"
            )
        markets.append({"name": name, "path": str(path), "reports": reports})

    windows = {}
    required_markets = 3
    for window in WINDOWS:
        selected = [market["reports"][str(window)] for market in markets]
        pooled = funding_carry_return_summary(
            [value for report in selected for value in report["net_returns_pct"]],
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
        )
        admitted_markets = sum(bool(report["admitted"]) for report in selected)
        stage_admitted = (
            admitted_markets >= required_markets
            and pooled["mean_net_carry_pct"] > 0
            and pooled["bootstrap_mean_ci_low"] > 0
        )
        windows[str(window)] = {
            "holding_days": window / 3,
            "admitted_markets": admitted_markets,
            "required_markets": required_markets,
            "pooled": pooled,
            "stage_admitted": stage_admitted,
        }
        print(
            f"portfolio days={window / 3:.0f} markets={admitted_markets}/4 "
            f"net={pooled['mean_net_carry_pct']:+.4f}% "
            f"ci_low={pooled['bootstrap_mean_ci_low']:+.4f}% "
            f"stage={'PASS' if stage_admitted else 'FAIL'}"
        )

    report = {
        "assumption": "optimistic_funding_only_upper_bound",
        "entry_exit_cost_pct": args.entry_exit_cost_pct,
        "rebalance_cost_pct_per_day": args.rebalance_cost_pct_per_day,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.bootstrap_seed,
        "markets": markets,
        "windows": windows,
        "stage_admitted": any(item["stage_admitted"] for item in windows.values()),
    }
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
