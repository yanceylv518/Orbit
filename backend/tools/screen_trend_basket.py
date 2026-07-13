"""Run the frozen TB1 trend-basket training and conditional lockbox audit."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.calibration.history import load_candles, load_funding  # noqa: E402
from orbit.domain.calibration.trend_basket import (  # noqa: E402
    trend_basket_data_quality,
    trend_basket_report,
)


FORMAL_UNIVERSE = {
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "LTCUSDT", "BCHUSDT",
}
MOMENTUM_DAYS = (28, 84, 168)
VOLATILITY_DAYS = (28, 84)
REBALANCE_DAYS = 7
LOCKBOX_DAYS = 365
LOCKBOX_MARKER = Path("var/research/tb1_lockbox_opened.json")
CORRECTION_MARKER = Path("var/research/tb1_lockbox_correction.json")


def parse_dataset(value: str) -> tuple[str, Path, Path]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "dataset must be NAME,CANDLE_PATH,FUNDING_PATH"
        )
    return parts[0].upper(), Path(parts[1]), Path(parts[2])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_config(report: dict) -> dict:
    return {
        key: value
        for key, value in report.items()
        if key not in {"net_returns_pct", "rebalances"}
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, type=parse_dataset)
    parser.add_argument("--mode", choices=("smoke", "formal"), default="smoke")
    parser.add_argument("--interval-hours", type=int, required=True)
    parser.add_argument("--open-lockbox", action="store_true")
    parser.add_argument("--correct-opened-lockbox", action="store_true")
    parser.add_argument("--correction-reason")
    parser.add_argument("--training-report")
    parser.add_argument("--training-report-sha256")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if args.interval_hours < 1 or 24 % args.interval_hours:
        parser.error("interval-hours must be a positive divisor of 24")
    names = [name for name, _, _ in args.dataset]
    if len(names) != len(set(names)):
        parser.error("dataset names must be unique")
    if args.mode == "formal" and set(names) != FORMAL_UNIVERSE:
        parser.error("formal mode requires the frozen 12-market universe")
    if args.open_lockbox and (
        args.mode != "formal"
        or not args.training_report
        or not args.training_report_sha256
    ):
        parser.error("lockbox requires formal mode, training report, and frozen SHA-256")
    if args.correct_opened_lockbox and (
        not args.open_lockbox or not args.correction_reason
    ):
        parser.error("lockbox correction requires --open-lockbox and a reason")
    if args.correction_reason and not args.correct_opened_lockbox:
        parser.error("--correction-reason is only valid for a lockbox correction")
    if not args.open_lockbox and args.training_report:
        parser.error("--training-report is only valid with --open-lockbox")
    if not args.open_lockbox and args.training_report_sha256:
        parser.error("--training-report-sha256 is only valid with --open-lockbox")
    if args.json_output and Path(args.json_output).exists():
        parser.error("json-output already exists; TB1 results are append-only")

    interval_ms = args.interval_hours * 3_600_000
    markets = {
        name: (load_candles(candle_path), load_funding(funding_path))
        for name, candle_path, funding_path in args.dataset
    }
    inputs = {
        name: {
            "candle_path": str(candle_path),
            "candle_sha256": sha256(candle_path),
            "funding_path": str(funding_path),
            "funding_sha256": sha256(funding_path),
        }
        for name, candle_path, funding_path in args.dataset
    }
    quality = trend_basket_data_quality(
        markets,
        interval_ms=interval_ms,
        min_markets=10,
        min_span_days=1_095,
        min_funding_coverage=0.99,
    )
    if args.mode == "formal" and quality["common_end_ms"] is not None:
        training_end_ms = quality["common_end_ms"] - LOCKBOX_DAYS * 86_400_000
        lockbox_start_ms = training_end_ms
    else:
        training_end_ms = None
        lockbox_start_ms = None

    if args.open_lockbox:
        training_path = Path(args.training_report)
        training = json.loads(training_path.read_text(encoding="utf-8"))
        if (
            training.get("protocol") != "TB1_TREND_BASKET"
            or training.get("mode") != "formal"
            or training.get("verdict") != "TRAINING_PASS_LOCKBOX_PENDING"
            or not training.get("selected_candidate")
        ):
            parser.error("training report is not an eligible frozen TB1 candidate")
        if training.get("inputs") != inputs:
            parser.error("current input fingerprints differ from the frozen training report")
        training_hash = sha256(training_path)
        if training_hash != args.training_report_sha256.lower():
            parser.error("training report SHA-256 differs from the frozen value")
        selected = training["selected_candidate"]
        if args.correct_opened_lockbox:
            if not LOCKBOX_MARKER.exists():
                parser.error("cannot correct a lockbox that has not been opened")
            original_marker = json.loads(LOCKBOX_MARKER.read_text(encoding="utf-8"))
            if original_marker.get("candidate_id") != selected["id"]:
                parser.error("corrected training selected a different candidate")
            if CORRECTION_MARKER.exists():
                parser.error("TB1 lockbox correction has already been used")
            CORRECTION_MARKER.parent.mkdir(parents=True, exist_ok=True)
            CORRECTION_MARKER.write_text(json.dumps({
                "protocol": "TB1_TREND_BASKET",
                "corrected_at": datetime.now(timezone.utc).isoformat(),
                "reason": args.correction_reason,
                "original_marker": str(LOCKBOX_MARKER),
                "original_marker_sha256": sha256(LOCKBOX_MARKER),
                "corrected_training_report": str(training_path),
                "corrected_training_report_sha256": training_hash,
                "candidate_id": selected["id"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            if LOCKBOX_MARKER.exists():
                parser.error("TB1 lockbox has already been opened")
            LOCKBOX_MARKER.parent.mkdir(parents=True, exist_ok=True)
            LOCKBOX_MARKER.write_text(json.dumps({
                "protocol": "TB1_TREND_BASKET",
                "opened_at": datetime.now(timezone.utc).isoformat(),
                "training_report": str(training_path),
                "training_report_sha256": training_hash,
                "candidate_id": selected["id"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        frozen = selected["training"]
        lockbox = trend_basket_report(
            markets,
            frozen["momentum_lookback"],
            frozen["volatility_lookback"],
            frozen["rebalance_ticks"],
            interval_ms=interval_ms,
            target_portfolio_vol=0.10,
            gross_cap=1.0,
            roundtrip_cost_pct=0.14,
            evaluation_start_ms=training["lockbox_start_ms"],
            min_markets=10,
            min_span_days=1_095,
            min_funding_coverage=0.99,
            fold_days=365,
        )
        report = {
            "protocol": "TB1_TREND_BASKET",
            "mode": (
                "formal_lockbox_correction"
                if args.correct_opened_lockbox
                else "formal_lockbox"
            ),
            "verdict": "PASS" if lockbox["admitted"] else "LOCKBOX_FAIL",
            "interval_hours": args.interval_hours,
            "inputs": inputs,
            "data_quality": quality,
            "training_report": str(training_path),
            "training_report_sha256": training_hash,
            "selected_candidate": selected,
            "lockbox_opened": True,
            "correction_reason": args.correction_reason,
            "lockbox": compact_config(lockbox),
        }
        print(
            f"lockbox candidate={selected['id']} "
            f"ann={lockbox['annualized_net_return_pct']:+.3f}% "
            f"sharpe={lockbox['sharpe']:+.3f} "
            f"dd={lockbox['max_drawdown_pct']:.3f}% "
            f"verdict={report['verdict']}"
        )
        if args.json_output:
            output = Path(args.json_output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
            )
            print(f"wrote {output}")
        return

    configurations = []
    for momentum_days, volatility_days in itertools.product(
        MOMENTUM_DAYS, VOLATILITY_DAYS,
    ):
        momentum_ticks = momentum_days * 24 // args.interval_hours
        volatility_ticks = volatility_days * 24 // args.interval_hours
        rebalance_ticks = REBALANCE_DAYS * 24 // args.interval_hours
        result = trend_basket_report(
            markets,
            momentum_ticks,
            volatility_ticks,
            rebalance_ticks,
            interval_ms=interval_ms,
            target_portfolio_vol=0.10,
            gross_cap=1.0,
            roundtrip_cost_pct=0.14,
            evaluation_end_ms=training_end_ms,
            min_markets=10,
            min_span_days=1_095,
            min_funding_coverage=0.99,
            fold_days=365,
        )
        item = {
            "id": f"mom{momentum_days}_vol{volatility_days}",
            "momentum_days": momentum_days,
            "volatility_days": volatility_days,
            "training": compact_config(result),
            "training_performance_pass": result["performance_bar_pass"],
            "training_admitted": result["admitted"],
        }
        configurations.append(item)
        print(
            f"{item['id']} years={result['years']:.2f} "
            f"ann={result['annualized_net_return_pct']:+.3f}% "
            f"sharpe={result['sharpe']:+.3f} "
            f"dd={result['max_drawdown_pct']:.3f}% "
            f"folds={result['profitable_folds']}/{result['folds']} "
            f"verdict={result['verdict']}"
        )

    candidates = [item for item in configurations if item["training_admitted"]]
    candidates.sort(
        key=lambda item: (
            item["training"]["sharpe"],
            item["training"]["annualized_net_return_pct"],
            -item["training"]["max_drawdown_pct"],
            item["momentum_days"],
            item["volatility_days"],
        ),
        reverse=True,
    )
    selected = candidates[0] if candidates else None
    if not quality["admitted"] or args.mode == "smoke":
        verdict = "DATA_LIMITED_NON_CONCLUSIVE"
    elif selected is None:
        verdict = "TRAINING_FAIL"
    else:
        verdict = "TRAINING_PASS_LOCKBOX_PENDING"
    report = {
        "protocol": "TB1_TREND_BASKET",
        "mode": args.mode,
        "verdict": verdict,
        "interval_hours": args.interval_hours,
        "inputs": inputs,
        "data_quality": quality,
        "training_end_ms": training_end_ms,
        "lockbox_start_ms": lockbox_start_ms,
        "lockbox_opened": False,
        "configuration_count": len(configurations),
        "configurations": configurations,
        "selected_candidate": selected,
        "lockbox": None,
    }
    print(
        f"selected={selected['id'] if selected else 'NONE'} "
        f"lockbox_opened=False verdict={verdict}"
    )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}")


if __name__ == "__main__":
    main()
