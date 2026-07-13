"""Replay historical closes through the production EventEngine paper logic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config  # noqa: E402
from orbit.domain.calibration.history import load_candles, load_funding  # noqa: E402
from orbit.domain.calibration.replay import replay_event_engine, replay_walk_forward  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--klines", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--budget", type=float, default=100.0)
    parser.add_argument("--config", default=str(ROOT / "config" / "config.sample.json"))
    parser.add_argument("--strategy-index", type=int, default=0)
    parser.add_argument("--no-close-out", action="store_true")
    parser.add_argument("--train-size", type=int)
    parser.add_argument("--validation-size", type=int)
    parser.add_argument("--step", type=int)
    parser.add_argument("--json-output")
    parser.add_argument("--funding")
    parser.add_argument(
        "--intrabar-mode",
        choices=("close_only", "myopic", "fixed_ohlc", "fixed_olhc"),
        default="close_only",
    )
    args = parser.parse_args()

    candles = load_candles(args.klines)
    closes = [candle.close for candle in candles]
    candle_times = [candle.close_time_ms for candle in candles]
    funding = load_funding(args.funding) if args.funding else None
    config = load_config(args.config)
    strategy = config["strategy_instances"][args.strategy_index]
    if args.train_size or args.validation_size:
        if not args.train_size or not args.validation_size:
            parser.error("--train-size and --validation-size must be provided together")
        report = replay_walk_forward(
            closes,
            strategy,
            symbol=args.symbol.upper(),
            budget_usdt=args.budget,
            train_size=args.train_size,
            validation_size=args.validation_size,
            step=args.step,
            candle_times_ms=candle_times,
            funding_points=funding,
            intrabar_candles=candles if args.intrabar_mode != "close_only" else None,
            intrabar_mode=args.intrabar_mode if args.intrabar_mode != "close_only" else "myopic",
        )
    else:
        report = replay_event_engine(
            closes,
            strategy,
            symbol=args.symbol.upper(),
            budget_usdt=args.budget,
            close_out=not args.no_close_out,
            candle_times_ms=candle_times,
            funding_points=funding,
            intrabar_candles=candles if args.intrabar_mode != "close_only" else None,
            intrabar_mode=args.intrabar_mode if args.intrabar_mode != "close_only" else "myopic",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
