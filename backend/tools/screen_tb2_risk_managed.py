"""Run the preregistered TB2 risk-managed trend-basket walk-forward."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import load_candles, load_funding  # noqa: E402
from orbit.domain.calibration.trend_basket import (  # noqa: E402
    trend_basket_walk_forward,
)


FORMAL_UNIVERSE = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
}
INTERVAL_MS = 4 * 3_600_000
YEAR_TICKS = 365 * 6
RUN_MARKER = Path("var/research/tb2_walk_forward_run.json")
CANDIDATES = (
    {"id": "vol06_none", "target_portfolio_vol": 0.06},
    {"id": "vol08_none", "target_portfolio_vol": 0.08},
    {
        "id": "vol10_dd10", "target_portfolio_vol": 0.10,
        "drawdown_threshold_pct": 10.0, "drawdown_risk_scale": 0.5,
    },
    {
        "id": "vol10_dd15", "target_portfolio_vol": 0.10,
        "drawdown_threshold_pct": 15.0, "drawdown_risk_scale": 0.5,
    },
    {
        "id": "vol06_dd10", "target_portfolio_vol": 0.06,
        "drawdown_threshold_pct": 10.0, "drawdown_risk_scale": 0.5,
    },
    {
        "id": "vol06_dd15", "target_portfolio_vol": 0.06,
        "drawdown_threshold_pct": 15.0, "drawdown_risk_scale": 0.5,
    },
    {
        "id": "vol08_dd10", "target_portfolio_vol": 0.08,
        "drawdown_threshold_pct": 10.0, "drawdown_risk_scale": 0.5,
    },
    {
        "id": "vol08_dd15", "target_portfolio_vol": 0.08,
        "drawdown_threshold_pct": 15.0, "drawdown_risk_scale": 0.5,
    },
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_result(report: dict, *, keep_risk_trajectory: bool = False) -> dict:
    compact = {
        key: value
        for key, value in report.items()
        if key not in {"net_returns_pct", "rebalances", "data_quality"}
    }
    if keep_risk_trajectory:
        compact["risk_trajectory"] = [
            {
                "signal_time_ms": item["signal_time_ms"],
                "execution_time_ms": item["execution_time_ms"],
                "drawdown_at_signal_pct": item["drawdown_at_signal_pct"],
                "risk_scale": item["risk_scale"],
                "gross_exposure": item["gross_exposure"],
            }
            for item in report["rebalances"]
        ]
    return compact


def compact_walk_forward(result: dict) -> dict:
    steps = []
    for step in result["steps"]:
        steps.append({
            **{
                key: value for key, value in step.items()
                if key not in {"training_candidates", "oos", "baseline"}
            },
            "training_candidates": [
                {
                    "candidate": item["candidate"],
                    "report": compact_result(item["report"]),
                }
                for item in step["training_candidates"]
            ],
            "oos": (
                compact_result(step["oos"], keep_risk_trajectory=True)
                if step["oos"] else None
            ),
            "baseline": (
                compact_result(step["baseline"])
                if step["baseline"] else None
            ),
        })
    return {
        key: value
        for key, value in result.items()
        if key not in {"steps", "aggregate_net_returns_pct"}
    } | {"steps": steps}


def frozen_windows(lockbox_start_ms: int) -> list[dict[str, int | str]]:
    second_end = lockbox_start_ms - INTERVAL_MS
    second_start = second_end - (YEAR_TICKS - 1) * INTERVAL_MS
    first_end = second_start - INTERVAL_MS
    first_start = first_end - (YEAR_TICKS - 1) * INTERVAL_MS
    return [
        {
            "id": "WF1",
            "training_end_ms": first_start - INTERVAL_MS,
            "oos_start_ms": first_start,
            "oos_end_ms": first_end,
        },
        {
            "id": "WF2",
            "training_end_ms": second_start - INTERVAL_MS,
            "oos_start_ms": second_start,
            "oos_end_ms": second_end,
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tb1-training-report", required=True)
    parser.add_argument("--tb1-training-report-sha256", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()

    training_path = Path(args.tb1_training_report)
    output_path = Path(args.json_output)
    if output_path.exists():
        parser.error("json-output already exists; TB2 results are append-only")
    if RUN_MARKER.exists():
        parser.error("the formal TB2 walk-forward has already been run")
    training_hash = sha256(training_path)
    if training_hash != args.tb1_training_report_sha256.lower():
        parser.error("TB1 training report SHA-256 differs from the frozen value")

    training = json.loads(training_path.read_text(encoding="utf-8"))
    selected = training.get("selected_candidate") or {}
    if (
        training.get("protocol") != "TB1_TREND_BASKET"
        or training.get("mode") != "formal"
        or training.get("verdict") != "TRAINING_PASS_LOCKBOX_PENDING"
        or selected.get("id") != "mom28_vol28"
    ):
        parser.error("report is not the corrected frozen TB1 training source")
    inputs = training.get("inputs") or {}
    if set(inputs) != FORMAL_UNIVERSE:
        parser.error("TB1 source does not contain the frozen 12-market universe")

    markets = {}
    verified_inputs = {}
    for name, item in inputs.items():
        candle_path = Path(item["candle_path"])
        funding_path = Path(item["funding_path"])
        candle_hash = sha256(candle_path)
        funding_hash = sha256(funding_path)
        if (
            candle_hash != item["candle_sha256"]
            or funding_hash != item["funding_sha256"]
        ):
            parser.error(f"{name} input fingerprint differs from TB1")
        markets[name] = (load_candles(candle_path), load_funding(funding_path))
        verified_inputs[name] = {
            "candle_path": str(candle_path),
            "candle_sha256": candle_hash,
            "funding_path": str(funding_path),
            "funding_sha256": funding_hash,
        }

    lockbox_start_ms = int(training["lockbox_start_ms"])
    windows = frozen_windows(lockbox_start_ms)
    frozen = selected["training"]
    result = trend_basket_walk_forward(
        markets,
        CANDIDATES,
        windows,
        interval_ms=INTERVAL_MS,
        momentum_lookback=int(frozen["momentum_lookback"]),
        volatility_lookback=int(frozen["volatility_lookback"]),
        rebalance_ticks=int(frozen["rebalance_ticks"]),
        gross_cap=1.0,
        roundtrip_cost_pct=0.14,
        min_markets=10,
        min_span_days=1_095,
        min_funding_coverage=0.99,
        fold_days=365,
    )
    report = {
        "protocol": "TB2_RISK_MANAGED_TREND_BASKET",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": result["verdict"],
        "tb1_training_report": str(training_path),
        "tb1_training_report_sha256": training_hash,
        "tb1_lockbox_start_ms_excluded": lockbox_start_ms,
        "inputs": verified_inputs,
        "windows": windows,
        "walk_forward": compact_walk_forward(result),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    report_hash = hashlib.sha256(serialized).hexdigest()
    RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
    RUN_MARKER.write_text(json.dumps({
        "protocol": report["protocol"],
        "run_at": report["generated_at"],
        "tb1_training_report": str(training_path),
        "tb1_training_report_sha256": training_hash,
        "output": str(output_path),
        "output_sha256": report_hash,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(serialized)

    for step in result["steps"]:
        oos = step["oos"]
        if oos is None:
            print(f"{step['id']} selected=NONE verdict=TRAINING_FAIL")
            continue
        print(
            f"{step['id']} selected={step['selected_candidate']['id']} "
            f"ann={oos['annualized_net_return_pct']:+.3f}% "
            f"sharpe={oos['sharpe']:+.3f} "
            f"dd={oos['max_drawdown_pct']:.3f}% "
            f"verdict={step['oos_verdict']}"
        )
    aggregate = result["aggregate"]
    print(
        f"aggregate ann={aggregate['annualized_net_return_pct']:+.3f}% "
        f"sharpe={aggregate['sharpe']:+.3f} "
        f"dd={aggregate['max_drawdown_pct']:.3f}% "
        f"verdict={result['verdict']}"
    )
    print(f"wrote {output_path} sha256={report_hash}")


if __name__ == "__main__":
    main()
