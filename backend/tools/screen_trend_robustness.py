"""Run the preregistered TB-R sensitivity and multi-horizon audit."""

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
    trend_basket_robustness_report,
)


FORMAL_UNIVERSE = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
}
INTERVAL_MS = 4 * 3_600_000
OOS_TICKS = 608 * 6
RUN_MARKER = Path("var/research/tb_r_robustness_run.json")


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
        {"id": "WF1", "oos_start_ms": first_start, "oos_end_ms": first_end},
        {"id": "WF2", "oos_start_ms": second_start, "oos_end_ms": second_end},
    ]


def compact_performance(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if key not in {
            "net_returns_pct", "rebalances", "data_quality", "rolling_returns_pct",
        }
    }


def compact_evaluation(result: dict) -> dict:
    return {
        key: value
        for key, value in result.items()
        if key not in {"steps", "aggregate_net_returns_pct", "aggregate"}
    } | {
        "steps": [
            {
                **{key: value for key, value in step.items() if key != "report"},
                "report": compact_performance(step["report"]),
            }
            for step in result["steps"]
        ],
        "aggregate": compact_performance(result["aggregate"]),
    }


def compact_report(result: dict) -> dict:
    return {
        "evidence_level": result["evidence_level"],
        "data_quality": result["data_quality"],
        "sensitivity_grid_count": result["sensitivity_grid_count"],
        "sensitivity_surface": [
            {
                "id": item["id"],
                "lookback_days": item["lookback_days"],
                "rebalance_days": item["rebalance_days"],
                **compact_evaluation(item),
            }
            for item in result["sensitivity_surface"]
        ],
        "smoothness": result["smoothness"],
        "ensemble": compact_evaluation(result["ensemble"]),
        "tb4_candidate": result["tb4_candidate"],
        "admitted": result["admitted"],
        "verdict": result["verdict"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tb1-training-report", required=True)
    parser.add_argument("--tb1-training-report-sha256", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()

    source_path = Path(args.tb1_training_report)
    output_path = Path(args.json_output)
    if output_path.exists():
        parser.error("json-output already exists; TB-R results are append-only")
    if RUN_MARKER.exists():
        parser.error("the formal TB-R robustness audit has already been run")
    source_hash = sha256(source_path)
    if source_hash != args.tb1_training_report_sha256.lower():
        parser.error("TB1 training report SHA-256 differs from the frozen value")

    source = json.loads(source_path.read_text(encoding="utf-8"))
    selected = source.get("selected_candidate") or {}
    if (
        source.get("protocol") != "TB1_TREND_BASKET"
        or source.get("mode") != "formal"
        or source.get("verdict") != "TRAINING_PASS_LOCKBOX_PENDING"
        or selected.get("id") != "mom28_vol28"
    ):
        parser.error("report is not the corrected frozen TB1 training source")
    inputs = source.get("inputs") or {}
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

    windows = frozen_windows(int(source["data_quality"]["common_end_ms"]))
    result = trend_basket_robustness_report(
        markets,
        windows,
        interval_ms=INTERVAL_MS,
        sensitivity_lookback_days=(7, 14, 28, 56, 84, 168),
        sensitivity_rebalance_days=(3, 7, 14),
        ensemble_lookback_days=(14, 28, 56, 84, 168),
        volatility_lookback_days=28,
        ensemble_rebalance_days=7,
        target_portfolio_vol=0.10,
        gross_cap=1.0,
        roundtrip_cost_pct=0.14,
        min_markets=10,
        min_span_days=1_095,
        min_funding_coverage=0.99,
    )
    report = {
        "protocol": "TB_R_TREND_ROBUSTNESS",
        "evidence_level": "BACKTEST_CONFIRMATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "verdict": result["verdict"],
        "tb1_training_report": str(source_path),
        "tb1_training_report_sha256": source_hash,
        "inputs": verified_inputs,
        "windows": windows,
        "result": compact_report(result),
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    report_hash = hashlib.sha256(serialized).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
    RUN_MARKER.write_text(json.dumps({
        "protocol": report["protocol"],
        "evidence_level": report["evidence_level"],
        "run_at": report["generated_at"],
        "tb1_training_report": str(source_path),
        "tb1_training_report_sha256": source_hash,
        "output": str(output_path),
        "output_sha256": report_hash,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    output_path.write_bytes(serialized)

    for item in result["sensitivity_surface"]:
        aggregate = item["aggregate"]
        print(
            f"{item['id']} ann={aggregate['annualized_net_return_pct']:+.3f}% "
            f"calmar={aggregate['calmar']:+.3f} "
            f"sortino={aggregate['sortino']:+.3f} "
            f"dd={aggregate['max_drawdown_pct']:.3f}% "
            f"verdict={item['verdict']}"
        )
    ensemble = result["ensemble"]["aggregate"]
    print(
        f"smoothness={result['smoothness']['verdict']} "
        f"support={result['smoothness']['supportive_axis_count']}/4"
    )
    print(
        f"ensemble ann={ensemble['annualized_net_return_pct']:+.3f}% "
        f"calmar={ensemble['calmar']:+.3f} "
        f"sortino={ensemble['sortino']:+.3f} "
        f"dd={ensemble['max_drawdown_pct']:.3f}% "
        f"verdict={result['ensemble']['verdict']}"
    )
    print(f"final={result['verdict']} wrote={output_path} sha256={report_hash}")


if __name__ == "__main__":
    main()
