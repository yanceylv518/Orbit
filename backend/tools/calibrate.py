"""Estimate strategy geometry and compare Regime Gate with walk-forward validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (  # noqa: E402
    estimate,
    geometry_scan,
    walk_forward_compare,
)


DEFAULT_A_GRID = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
DEFAULT_THETA_GRID = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]


def load_closes(path: str) -> list[float]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return [float(row[1]) for row in rows]


def print_report(report: dict) -> None:
    verdict = "PASS" if report["admitted"] else "FAIL"
    print(f"a={report['a_pct']:.2f}% theta={report['theta_pct']:.2f}% cost={report['cost_pct']:.2f}%")
    print(
        f"  excursions={report['excursions']} reversions={report['reversions']} "
        f"extensions={report['extensions']}"
    )
    print(
        f"  pi={report['pi_hat']:.3f} CI=[{report['pi_ci_low']:.3f}, "
        f"{report['pi_ci_high']:.3f}] pi_required={report['pi_required']:.3f}"
    )
    print(
        f"  EV={report['expected_value_pct']:+.3f}% total={report['total_return_pct']:+.3f}% "
        f"max_drawdown={report['max_drawdown_pct']:.3f}% C8={verdict}"
    )


def print_walk_forward(result: dict) -> None:
    print(
        f"walk-forward train={result['train_size']} validation={result['validation_size']} "
        f"step={result['step']} folds={len(result['folds'])}"
    )
    for fold in result["folds"]:
        off = fold["gate_off"]
        on = fold["gate_on"]
        print(
            f"  fold={fold['fold']:02d} validation=[{fold['train_end']},{fold['validation_end']}) "
            f"a={fold['selected_a_pct']:.2f} theta={fold['selected_theta_pct']:.2f} "
            f"off_EV={off['expected_value_pct']:+.3f}% "
            f"on_EV={on['expected_value_pct']:+.3f}% "
            f"filtered={on['filtered_entries']}"
        )
    print("\naggregate")
    for name in ("gate_off", "gate_on"):
        report = result["aggregate"][name]
        print(
            f"  {name}: trades={report['excursions']} frequency={report['trade_frequency']:.3f} "
            f"EV={report['expected_value_pct']:+.3f}% total={report['total_return_pct']:+.3f}% "
            f"worst_fold_DD={report['worst_fold_drawdown_pct']:.3f}% "
            f"profitable_folds={report['profitable_folds']}/{report['folds']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--klines", required=True, help="JSON produced by fetch_klines.py")
    parser.add_argument("--a", type=float, default=1.5, help="entry excursion percentage")
    parser.add_argument("--theta", type=float, default=4.0, help="trend confirmation percentage")
    parser.add_argument("--cost", type=float, default=0.14, help="round-trip cost percentage")
    parser.add_argument("--scan", action="store_true", help="scan the default geometry grid")
    parser.add_argument("--walk-forward", action="store_true", help="compare Gate off/on out of sample")
    parser.add_argument("--train-size", type=int, default=2880, help="training candles per fold")
    parser.add_argument("--validation-size", type=int, default=960, help="validation candles per fold")
    parser.add_argument("--step", type=int, help="candles between fold starts; defaults to validation size")
    parser.add_argument("--json-output", help="write the complete result to this JSON file")
    args = parser.parse_args()

    closes = load_closes(args.klines)
    print(f"loaded {len(closes)} closes")

    if args.walk_forward:
        result = walk_forward_compare(
            closes,
            DEFAULT_A_GRID,
            DEFAULT_THETA_GRID,
            args.cost,
            train_size=args.train_size,
            validation_size=args.validation_size,
            step=args.step,
        )
        print_walk_forward(result)
    elif args.scan:
        result = geometry_scan(closes, DEFAULT_A_GRID, DEFAULT_THETA_GRID, args.cost)
        for report in result[:20]:
            print_report(report)
    else:
        result = estimate(closes, args.a, args.theta, args.cost)
        print_report(result)

    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
