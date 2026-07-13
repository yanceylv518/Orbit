"""Run reproducible walk-forward calibration across multiple market datasets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (  # noqa: E402
    default_gate_config_grid,
    portfolio_calibration_summary,
    walk_forward_compare,
)
from orbit.domain.calibration.history import load_candles  # noqa: E402


A_GRID = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]
THETA_GRID = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0]


def parse_dataset(value: str) -> tuple[str, Path, int, int]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("dataset must be NAME,PATH,TRAIN_SIZE,VALIDATION_SIZE")
    name, path, train_size, validation_size = parts
    return name, Path(path), int(train_size), int(validation_size)


def load_closes(path: Path) -> list[float]:
    return [candle.close for candle in load_candles(path)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        type=parse_dataset,
        help="repeatable NAME,PATH,TRAIN_SIZE,VALIDATION_SIZE",
    )
    parser.add_argument("--cost", type=float, default=0.14)
    parser.add_argument("--tune-gate", action="store_true", help="select Gate config using training data only")
    parser.add_argument("--json-output")
    args = parser.parse_args()

    markets = []
    for name, path, train_size, validation_size in args.dataset:
        closes = load_closes(path)
        result = walk_forward_compare(
            closes,
            A_GRID,
            THETA_GRID,
            args.cost,
            train_size=train_size,
            validation_size=validation_size,
            gate_config_grid=default_gate_config_grid() if args.tune_gate else None,
        )
        markets.append({"name": name, "path": str(path), "closes": len(closes), "result": result})

    summaries = {
        comparison: portfolio_calibration_summary(markets, args.cost, comparison=comparison)
        for comparison in ("gate_off", "gate_on", "gate_deploy")
    }
    report = {
        "cost_pct": args.cost,
        "gate_tuning_enabled": args.tune_gate,
        "markets": markets,
        "summary": summaries,
    }

    for market in markets:
        print(f"{market['name']} closes={market['closes']} folds={len(market['result']['folds'])}")
        for comparison in ("gate_off", "gate_on", "gate_deploy"):
            item = market["result"]["aggregate"][comparison]
            print(
                f"  {comparison}: trades={item['excursions']} EV={item['expected_value_pct']:+.3f}% "
                f"gross={item['gross_return_pct']:+.3f}% fees=-{item['fee_drag_pct']:.3f}% "
                f"total={item['total_return_pct']:+.3f}% DD={item['worst_fold_drawdown_pct']:.3f}%"
            )
    print("portfolio")
    for comparison, item in summaries.items():
        verdict = "PASS" if item["stage_admitted"] else "FAIL"
        print(
            f"  {comparison}: trades={item['excursions']} EV={item['expected_value_pct']:+.3f}% "
            f"gross={item['gross_return_pct']:+.3f}% fees=-{item['fee_drag_pct']:.3f}% "
            f"total={item['total_return_pct']:+.3f}% filtered_cf="
            f"{item['filtered_counterfactual_net_return_pct']:+.3f}% "
            f"break_even_cost={item['break_even_cost_pct']:.3f}% profitable_markets="
            f"{item['profitable_markets']}/{item['markets']} stage={verdict}"
        )

    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
