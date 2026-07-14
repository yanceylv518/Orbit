"""Verify the frozen TB4 runner against the TB-R offline estimator."""

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
from orbit.domain.calibration.trend_basket import trend_basket_report  # noqa: E402
from orbit.domain.strategy.trend_basket_runner import (  # noqa: E402
    TB4_SPEC,
    replay_frozen_trend_basket,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tb1-training-report", required=True)
    parser.add_argument("--tb1-training-report-sha256", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()

    source_path = Path(args.tb1_training_report)
    if sha256(source_path) != args.tb1_training_report_sha256.lower():
        parser.error("TB1 training report SHA-256 differs from the frozen value")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    inputs = source.get("inputs") or {}
    if set(inputs) != set(TB4_SPEC.symbols):
        parser.error("TB1 source does not contain the frozen TB4 universe")

    markets = {}
    for symbol, item in inputs.items():
        candle_path = Path(item["candle_path"])
        funding_path = Path(item["funding_path"])
        if sha256(candle_path) != item["candle_sha256"]:
            parser.error(f"{symbol} candle fingerprint differs from TB1")
        if sha256(funding_path) != item["funding_sha256"]:
            parser.error(f"{symbol} funding fingerprint differs from TB1")
        markets[symbol] = (load_candles(candle_path), load_funding(funding_path))

    offline = trend_basket_report(
        markets,
        momentum_lookback=TB4_SPEC.momentum_lookbacks[0],
        momentum_lookbacks=TB4_SPEC.momentum_lookbacks,
        volatility_lookback=TB4_SPEC.volatility_lookback,
        rebalance_ticks=TB4_SPEC.rebalance_ticks,
        interval_ms=TB4_SPEC.interval_ms,
        target_portfolio_vol=TB4_SPEC.target_portfolio_vol,
        gross_cap=TB4_SPEC.gross_cap,
        roundtrip_cost_pct=TB4_SPEC.roundtrip_cost_pct,
        min_markets=len(TB4_SPEC.symbols),
        min_span_days=1_095,
        min_funding_coverage=0.99,
    )
    runner = replay_frozen_trend_basket(markets)
    tolerance = 1e-12
    max_return_error = max(
        abs(actual - expected)
        for actual, expected in zip(runner.net_returns_pct, offline["net_returns_pct"])
    )
    max_weight_error = max(
        abs(actual["target_weights"][symbol] - expected["target_weights"][symbol])
        for actual, expected in zip(runner.rebalances, offline["rebalances"])
        for symbol in TB4_SPEC.symbols
    )
    aligned = (
        len(runner.net_returns_pct) == len(offline["net_returns_pct"])
        and len(runner.rebalances) == len(offline["rebalances"])
        and max_return_error <= tolerance
        and max_weight_error <= tolerance
    )
    report = {
        "protocol": "TB4_RUNNER_ALIGNMENT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_path),
        "source_sha256": sha256(source_path),
        "symbols": list(TB4_SPEC.symbols),
        "periods": len(runner.net_returns_pct),
        "rebalances": len(runner.rebalances),
        "tolerance": tolerance,
        "max_return_error": max_return_error,
        "max_target_weight_error": max_weight_error,
        "aligned": aligned,
        "verdict": "TB4_ALIGNMENT_PASS" if aligned else "TB4_ALIGNMENT_FAIL",
    }
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not aligned:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
