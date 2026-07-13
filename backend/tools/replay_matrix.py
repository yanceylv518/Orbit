"""Run EventEngine walk-forward replay across multiple datasets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.config import load_config  # noqa: E402
from orbit.domain.calibration.history import exclude_latest_candles, load_candles, load_funding  # noqa: E402
from orbit.domain.calibration.replay import (  # noqa: E402
    aggregate_replay_markets,
    compare_replay_variants,
    replay_walk_forward,
    replay_walk_forward_tuned_loss_reduction,
)


def parse_dataset(value: str) -> tuple[str, str, Path, int, int, Path | None]:
    parts = value.split(",")
    if len(parts) not in (5, 6):
        raise argparse.ArgumentTypeError(
            "dataset must be NAME,SYMBOL,PATH,TRAIN_SIZE,VALIDATION_SIZE[,FUNDING_PATH]"
        )
    name, symbol, path, train_size, validation_size = parts[:5]
    return name, symbol, Path(path), int(train_size), int(validation_size), Path(parts[5]) if len(parts) == 6 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", required=True, type=parse_dataset)
    parser.add_argument("--config", default=str(ROOT / "config" / "config.sample.json"))
    parser.add_argument("--budget", type=float, default=100.0)
    parser.add_argument("--compare-variants", action="store_true")
    parser.add_argument("--variant", action="append")
    parser.add_argument("--tune-loss-reduction", action="store_true")
    parser.add_argument(
        "--intrabar-mode",
        choices=("close_only", "myopic", "fixed_ohlc", "fixed_olhc"),
        default="close_only",
    )
    parser.add_argument("--json-output")
    parser.add_argument("--exclude-latest-candles", type=int, default=0)
    args = parser.parse_args()
    if args.intrabar_mode != "close_only" and args.tune_loss_reduction:
        parser.error("intrabar mode cannot be combined with parameter tuning")

    strategy = load_config(args.config)["strategy_instances"][0]
    markets = []
    for name, symbol, path, train_size, validation_size, funding_path in args.dataset:
        candles = exclude_latest_candles(load_candles(path), args.exclude_latest_candles)
        closes = [candle.close for candle in candles]
        candle_times = [candle.close_time_ms for candle in candles]
        funding = load_funding(funding_path) if funding_path else None
        variants = compare_replay_variants(
            closes, strategy, symbol=symbol, train_size=train_size,
            validation_size=validation_size, budget_usdt=args.budget,
            candle_times_ms=candle_times, funding_points=funding,
            intrabar_candles=candles if args.intrabar_mode != "close_only" else None,
            intrabar_mode=args.intrabar_mode if args.intrabar_mode != "close_only" else "myopic",
            variants=args.variant,
        ) if args.compare_variants else None
        if args.tune_loss_reduction:
            result = replay_walk_forward_tuned_loss_reduction(
                closes, strategy, symbol=symbol, train_size=train_size,
                validation_size=validation_size, budget_usdt=args.budget,
            )
        else:
            result = (variants.get("full") or next(iter(variants.values()))) if variants else replay_walk_forward(
                closes, strategy, symbol=symbol, train_size=train_size,
                validation_size=validation_size, budget_usdt=args.budget,
                candle_times_ms=candle_times, funding_points=funding,
                intrabar_candles=candles if args.intrabar_mode != "close_only" else None,
                intrabar_mode=args.intrabar_mode if args.intrabar_mode != "close_only" else "myopic",
            )
        markets.append({"name": name, "path": str(path), "result": result, "variants": variants})

    summary = aggregate_replay_markets(markets)
    variant_summaries = {}
    if args.compare_variants:
        for variant in markets[0]["variants"]:
            variant_markets = [
                {"name": market["name"], "result": market["variants"][variant]}
                for market in markets
            ]
            variant_summaries[variant] = aggregate_replay_markets(variant_markets)
    report = {"markets": markets, "summary": summary, "variant_summaries": variant_summaries}
    for market in markets:
        item = market["result"]["aggregate"]
        print(
            f"{market['name']}: pnl={item['total_net_pnl_usdt']:+.3f} "
            f"profitable_folds={item['profitable_folds']}/{item['folds']} "
            f"worst_return={item['worst_fold_return_pct']:+.3f}%"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for variant, item in variant_summaries.items():
        print(
            f"variant={variant}: pnl={item['total_net_pnl_usdt']:+.3f} "
            f"markets={item['profitable_markets']}/{item['markets']} "
            f"folds={item['profitable_folds']}/{item['folds']}"
        )
    if summary.get("event_attribution"):
        print("event attribution (selected strategy)")
        for family, item in summary["event_attribution"].items():
            print(
                f"  {family}: events={item['events']} trades={item['trades']} "
                f"realized={item['realized_pnl_usdt']:+.3f} "
                f"fees={item['fee_usdt']:.3f} slippage={item['slippage_usdt']:.3f}"
            )
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
