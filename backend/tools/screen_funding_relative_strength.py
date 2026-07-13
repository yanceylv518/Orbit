"""Screen the frozen G2 cross-market funding relative-strength strategy."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (  # noqa: E402
    funding_relative_strength_report,
)
from orbit.domain.calibration.history import load_candles, load_funding  # noqa: E402


LOOKBACKS = (3, 9, 21)
HOLDINGS = (3, 9, 21)


def parse_dataset(value: str) -> tuple[str, Path, Path]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("dataset must be NAME,FUNDING_PATH,CANDLE_PATH")
    return parts[0], Path(parts[1]), Path(parts[2])


def config_id(lookback: int, holding: int) -> str:
    return f"lb{lookback}_h{holding}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, type=parse_dataset)
    parser.add_argument("--cost-pct", type=float, default=0.14)
    parser.add_argument("--min-market-appearances", type=int, default=10)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20_260_713)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if len(args.dataset) != 4:
        parser.error("the frozen G2 protocol requires exactly four datasets")
    names = [name for name, _, _ in args.dataset]
    if len(set(names)) != len(names):
        parser.error("dataset names must be unique")

    markets = {
        name: (load_funding(funding_path), load_candles(candle_path))
        for name, funding_path, candle_path in args.dataset
    }
    sources = {
        name: {
            "funding_path": str(funding_path),
            "candle_path": str(candle_path),
        }
        for name, funding_path, candle_path in args.dataset
    }
    configurations = []
    for lookback, holding in itertools.product(LOOKBACKS, HOLDINGS):
        raw = funding_relative_strength_report(
            markets,
            lookback,
            holding,
            cost_pct=args.cost_pct,
            min_market_appearances=args.min_market_appearances,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
        )
        item = {
            "id": config_id(lookback, holding),
            **{key: value for key, value in raw.items() if key != "records"},
        }
        configurations.append(item)
        coverage = ",".join(
            f"{name}:{count}" for name, count in item["market_appearances"].items()
        )
        print(
            f"{item['id']} events={item['events']} "
            f"net={item['mean_net_return_pct']:+.4f}% "
            f"ci_low={item['bootstrap_mean_ci_low']:+.4f}% "
            f"coverage={coverage} stage={'PASS' if item['admitted'] else 'FAIL'}"
        )

    candidates = [item for item in configurations if item["admitted"]]
    candidates.sort(
        key=lambda item: (
            item["bootstrap_mean_ci_low"],
            item["mean_net_return_pct"],
            item["events"],
            item["lookback_settlements"],
            -item["holding_settlements"],
        ),
        reverse=True,
    )
    diagnostic = max(
        configurations,
        key=lambda item: (
            item["bootstrap_mean_ci_low"],
            item["mean_net_return_pct"],
        ),
    )
    report = {
        "protocol": "G2_FUNDING_RELATIVE_STRENGTH",
        "direction": "long_highest_short_lowest",
        "cost_pct": args.cost_pct,
        "min_market_appearances": args.min_market_appearances,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.bootstrap_seed,
        "sources": sources,
        "configuration_count": len(configurations),
        "configurations": configurations,
        "candidate_count": len(candidates),
        "selected_candidate": candidates[0] if candidates else None,
        "best_diagnostic_config": diagnostic,
        "stage_admitted": bool(candidates),
    }
    print(
        "selected="
        + (candidates[0]["id"] if candidates else "NONE")
        + f" diagnostic={diagnostic['id']}"
    )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
