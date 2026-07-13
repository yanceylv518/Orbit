"""Screen frozen G1 contrarian reactions to extreme funding settlements."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.estimators import (  # noqa: E402
    extreme_funding_reaction_report,
    extreme_funding_return_summary,
)
from orbit.domain.calibration.history import load_candles, load_funding  # noqa: E402


LOOKBACKS = (90, 180, 360)
QUANTILES = (0.9, 0.95, 0.975)
HOLDING_TICKS = (4, 16, 32, 96)


def parse_dataset(value: str) -> tuple[str, Path, Path]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("dataset must be NAME,FUNDING_PATH,CANDLE_PATH")
    return parts[0], Path(parts[1]), Path(parts[2])


def config_id(lookback: int, quantile: float, holding_ticks: int) -> str:
    return f"lb{lookback}_q{quantile:g}_h{holding_ticks}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, type=parse_dataset)
    parser.add_argument("--cost-pct", type=float, default=0.14)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--bootstrap-seed", type=int, default=20_260_713)
    parser.add_argument("--required-markets", type=int, default=3)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if args.required_markets < 1 or args.required_markets > len(args.dataset):
        parser.error("required-markets must be between one and the dataset count")

    datasets = [
        {
            "name": name,
            "funding_path": str(funding_path),
            "candle_path": str(candle_path),
            "funding": load_funding(funding_path),
            "candles": load_candles(candle_path),
        }
        for name, funding_path, candle_path in args.dataset
    ]
    configurations = []
    for lookback, quantile, holding_ticks in itertools.product(
        LOOKBACKS,
        QUANTILES,
        HOLDING_TICKS,
    ):
        market_reports = []
        for dataset in datasets:
            raw = extreme_funding_reaction_report(
                dataset["funding"],
                dataset["candles"],
                lookback,
                quantile,
                holding_ticks,
                cost_pct=args.cost_pct,
                bootstrap_samples=args.bootstrap_samples,
                bootstrap_seed=args.bootstrap_seed,
            )
            market_reports.append({
                "name": dataset["name"],
                "funding_path": dataset["funding_path"],
                "candle_path": dataset["candle_path"],
                **{key: value for key, value in raw.items() if key != "records"},
            })

        pooled = extreme_funding_return_summary(
            [
                value
                for market in market_reports
                for value in market["net_returns_pct"]
            ],
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
        )
        admitted_markets = sum(bool(market["admitted"]) for market in market_reports)
        stage_admitted = (
            admitted_markets >= args.required_markets
            and pooled["mean_net_return_pct"] > 0
            and pooled["bootstrap_mean_ci_low"] > 0
        )
        item = {
            "id": config_id(lookback, quantile, holding_ticks),
            "lookback_settlements": lookback,
            "extreme_quantile": quantile,
            "holding_ticks": holding_ticks,
            "holding_hours": holding_ticks / 4,
            "admitted_markets": admitted_markets,
            "required_markets": args.required_markets,
            "markets": market_reports,
            "pooled": pooled,
            "stage_admitted": stage_admitted,
        }
        configurations.append(item)
        print(
            f"{item['id']} markets={admitted_markets}/{len(datasets)} "
            f"events={pooled['events']} net={pooled['mean_net_return_pct']:+.4f}% "
            f"ci_low={pooled['bootstrap_mean_ci_low']:+.4f}% "
            f"stage={'PASS' if stage_admitted else 'FAIL'}"
        )

    candidates = [item for item in configurations if item["stage_admitted"]]
    candidates.sort(
        key=lambda item: (
            item["pooled"]["bootstrap_mean_ci_low"],
            item["pooled"]["mean_net_return_pct"],
            item["pooled"]["events"],
            item["lookback_settlements"],
            item["extreme_quantile"],
            -item["holding_ticks"],
        ),
        reverse=True,
    )
    diagnostic = max(
        configurations,
        key=lambda item: (
            item["pooled"]["bootstrap_mean_ci_low"],
            item["pooled"]["mean_net_return_pct"],
        ),
    )
    report = {
        "protocol": "G1_EXTREME_FUNDING",
        "cost_pct": args.cost_pct,
        "bootstrap_samples": args.bootstrap_samples,
        "bootstrap_seed": args.bootstrap_seed,
        "required_markets": args.required_markets,
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
