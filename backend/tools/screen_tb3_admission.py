"""Run the preregistered TB3 backtest-confirmation walk-forward."""

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
    trend_basket_tb3_walk_forward,
)


FORMAL_UNIVERSE = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
}
INTERVAL_MS = 4 * 3_600_000
OOS_TICKS = 608 * 6
RUN_MARKER = Path("var/research/tb3_backtest_confirmation_run.json")
CANDIDATES = (
    {"id": "vol10", "target_portfolio_vol": 0.10},
    {"id": "vol15", "target_portfolio_vol": 0.15},
    {"id": "vol20", "target_portfolio_vol": 0.20},
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_windows(common_end_ms: int) -> list[dict[str, int | str]]:
    second_end = common_end_ms
    second_start = second_end - (OOS_TICKS - 1) * INTERVAL_MS
    first_end = second_start - INTERVAL_MS
    first_start = first_end - (OOS_TICKS - 1) * INTERVAL_MS
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


def compact_result(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if key not in {"net_returns_pct", "rebalances", "data_quality"}
    }


def compact_walk_forward(result: dict) -> dict:
    steps = []
    for step in result["steps"]:
        steps.append({
            **{
                key: value for key, value in step.items()
                if key not in {"training_candidates", "oos"}
            },
            "training_candidates": [
                {
                    "candidate": item["candidate"],
                    "training_eligible": item["training_eligible"],
                    "report": compact_result(item["report"]),
                }
                for item in step["training_candidates"]
            ],
            "oos": compact_result(step["oos"]) if step["oos"] else None,
        })
    return {
        key: value
        for key, value in result.items()
        if key not in {"steps", "aggregate_net_returns_pct"}
    } | {"steps": steps}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tb1-training-report", required=True)
    parser.add_argument("--tb1-training-report-sha256", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()

    training_path = Path(args.tb1_training_report)
    output_path = Path(args.json_output)
    if output_path.exists():
        parser.error("json-output already exists; TB3 results are append-only")
    if RUN_MARKER.exists():
        parser.error("the formal TB3 backtest confirmation has already been run")
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

    common_end_ms = int(training["data_quality"]["common_end_ms"])
    windows = frozen_windows(common_end_ms)
    frozen = selected["training"]
    result = trend_basket_tb3_walk_forward(
        markets,
        CANDIDATES,
        windows,
        interval_ms=INTERVAL_MS,
        momentum_lookback=int(frozen["momentum_lookback"]),
        volatility_lookback=int(frozen["volatility_lookback"]),
        rebalance_ticks=int(frozen["rebalance_ticks"]),
        training_max_drawdown_pct=25.0,
        gross_cap=1.0,
        roundtrip_cost_pct=0.14,
        min_markets=10,
        min_span_days=1_095,
        min_funding_coverage=0.99,
    )
    report = {
        "protocol": "TB3_TARGET_ALIGNED_ADMISSION",
        "evidence_level": "BACKTEST_CONFIRMATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": result["verdict"],
        "tb1_training_report": str(training_path),
        "tb1_training_report_sha256": training_hash,
        "inputs": verified_inputs,
        "windows": windows,
        "walk_forward": compact_walk_forward(result),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    report_hash = hashlib.sha256(serialized).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
    RUN_MARKER.write_text(json.dumps({
        "protocol": report["protocol"],
        "evidence_level": report["evidence_level"],
        "run_at": report["generated_at"],
        "tb1_training_report": str(training_path),
        "tb1_training_report_sha256": training_hash,
        "output": str(output_path),
        "output_sha256": report_hash,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path.write_bytes(serialized)

    for step in result["steps"]:
        oos = step["oos"]
        if oos is None:
            print(f"{step['id']} selected=NONE verdict=TRAINING_FAIL")
            continue
        print(
            f"{step['id']} selected={step['selected_candidate']['id']} "
            f"net={oos['total_net_return_pct']:+.3f}% "
            f"calmar={oos['calmar'] if oos['calmar'] is not None else 'INF'} "
            f"sortino={oos['sortino'] if oos['sortino'] is not None else 'INF'} "
            f"dd={oos['max_drawdown_pct']:.3f}% "
            f"verdict={step['oos_verdict']}"
        )
    aggregate = result["aggregate"]
    print(
        f"aggregate net={aggregate['total_net_return_pct']:+.3f}% "
        f"calmar={aggregate['calmar'] if aggregate['calmar'] is not None else 'INF'} "
        f"sortino={aggregate['sortino'] if aggregate['sortino'] is not None else 'INF'} "
        f"dd={aggregate['max_drawdown_pct']:.3f}% "
        f"verdict={result['verdict']}"
    )
    print(f"wrote {output_path} sha256={report_hash}")


if __name__ == "__main__":
    main()
