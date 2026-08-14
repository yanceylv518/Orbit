"""Generate the RC-0B non-predictive volume-reduction curves."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.rc0b_volume_curve import (  # noqa: E402
    DAY_MS,
    breakout_shape,
    distribution_summary,
    frequency_summary,
    large_opportunity_retention,
    select_combination,
)
from orbit.domain.calibration.r0_shortline import HistoricalUniverseResolver  # noqa: E402
from screen_r0_shortline import _load_universe_inputs, _market_loader  # noqa: E402


ROOT = PROJECT_ROOT / "var/calibration/shortline-data-v1"
SPEC_PATH = PROJECT_ROOT / "config/research/rc0b_volume_curve.v1.json"
SOURCE_REPORT_PATH = PROJECT_ROOT / "docs/evidence/rc0/rc0_funnel_v1_20260814.json"
SOURCE_DB = PROJECT_ROOT / "var/research/rc0-funnel-v1.sqlite"
THRESHOLDS = (30_000_000, 100_000_000, 200_000_000, 500_000_000)
CHANNELS = (32, 96, 288)
RELATIVE_VOLUMES = (1.5, 2.5, 4.0)

SCHEMA = """
create table events(
  family_id text not null,
  symbol text not null,
  signal_time_ms integer not null,
  direction text not null,
  relative_quote_volume real,
  breaks_channel_32 integer,
  breaks_channel_96 integer,
  breaks_channel_288 integer,
  eligible_30000000 integer not null,
  eligible_100000000 integer not null,
  eligible_200000000 integer not null,
  eligible_500000000 integer not null,
  large_opportunity integer,
  primary key(family_id,symbol,signal_time_ms,direction)
);
create table processed_symbols(symbol text primary key);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--source-db", default=str(SOURCE_DB))
    parser.add_argument("--markdown-out")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summarize-existing", action="store_true")
    args = parser.parse_args()

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    _verify_contract(spec)
    source = sqlite3.connect(Path(args.source_db))
    _verify_source_database(source, spec)
    contracts, liquidity = _load_universe_inputs(ROOT, maximum_time_ms=int(spec["training_end_ms"]))
    resolvers = _resolvers(contracts, liquidity, spec)
    target = _open_database(Path(args.db), resume=args.resume or args.summarize_existing)
    if not args.summarize_existing:
        loader = _market_loader(ROOT, minimum_time_ms=None, maximum_time_ms=int(spec["training_end_ms"]))
        _scan(source, target, resolvers, loader)
    report = _build_report(target, resolvers, contracts, spec)
    _write_json_lf_exclusive(Path(args.out), report)
    if args.markdown_out:
        _write_text_lf_exclusive(Path(args.markdown_out), _markdown(report))
    target.close()
    source.close()
    print(json.dumps({"output": args.out, "events": report["source_event_count"]}))


def _verify_contract(spec: dict[str, Any]) -> None:
    if int(spec["training_end_ms"]) >= int(spec["lockbox_start_ms"]):
        raise RuntimeError("training boundary reaches lockbox")
    if spec["discipline"]["lockbox_access"] != "PROHIBITED":
        raise RuntimeError("lockbox access is not prohibited")
    if tuple(spec["liquidity"]["thresholds_usdt"]) != THRESHOLDS:
        raise RuntimeError("liquidity thresholds differ from frozen RC-0B contract")
    if _sha256(SOURCE_REPORT_PATH) != spec["source_rc0_report_sha256"]:
        raise RuntimeError("source RC-0 report hash mismatch")


def _verify_source_database(source: sqlite3.Connection, spec: dict[str, Any]) -> None:
    total = source.execute("select count(*) from events").fetchone()[0]
    if total != int(spec["source_event_count"]):
        raise RuntimeError(f"source RC-0 event count mismatch: {total}")
    for family_id, expected in spec["source_pool"].items():
        actual = source.execute("select count(*) from events where family_id=?", (family_id,)).fetchone()[0]
        if actual != int(expected["event_count"]):
            raise RuntimeError(f"source RC-0 family count mismatch: {family_id}={actual}")


def _resolvers(contracts, liquidity, spec):
    tiering = {
        "method": "DYNAMIC_EQUAL_THIRDS_BY_LIQUIDITY_RANK",
        "ordered_tiers": ["HIGH", "MEDIUM", "LOW"],
        "remainder_allocation": "HIGH_THEN_MEDIUM",
        "minimum_qualified_contracts": int(
            spec["liquidity"]["minimum_qualified_contracts_per_snapshot"]
        ),
        "insufficient_qualified_contracts_policy": "EXCLUDE_ENTIRE_SNAPSHOT",
    }
    return {
        threshold: HistoricalUniverseResolver(
            contracts,
            liquidity,
            min_history_days=0,
            liquidity_lookback_days=3,
            minimum_volume=str(threshold),
            limit=None,
            tiering=tiering,
        )
        for threshold in THRESHOLDS
    }


def _open_database(path: Path, *, resume: bool) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if resume:
        if not path.exists():
            raise RuntimeError("RC-0B sqlite does not exist")
        connection = sqlite3.connect(path)
    else:
        if path.exists():
            raise RuntimeError("RC-0B sqlite already exists")
        connection = sqlite3.connect(path)
        connection.executescript(SCHEMA)
    connection.execute("pragma journal_mode=wal")
    connection.execute("pragma synchronous=normal")
    return connection


def _scan(source, target, resolvers, loader) -> None:
    completed = {row[0] for row in target.execute("select symbol from processed_symbols")}
    symbols = [row[0] for row in source.execute("select distinct symbol from events order by symbol")]
    source.row_factory = sqlite3.Row
    for offset, symbol in enumerate(symbols, start=1):
        if symbol in completed:
            continue
        source_rows = list(
            source.execute(
                "select family_id,symbol,signal_ms,direction,mfe_960_r from events where symbol=? "
                "order by signal_ms,family_id,direction",
                (symbol,),
            )
        )
        breakout_rows = [row for row in source_rows if row["family_id"] == "BREAKOUT_MOMENTUM"]
        shape_by_identity = {}
        if breakout_rows:
            candles, _ = loader(symbol)
            indexes = {row.close_time_ms: index for index, row in enumerate(candles)}
            for row in breakout_rows:
                identity = (int(row["signal_ms"]), str(row["direction"]))
                signal_index = indexes.get(identity[0])
                if signal_index is None:
                    raise RuntimeError(f"missing signal candle: {symbol} {identity[0]}")
                shape_by_identity[identity] = breakout_shape(candles, signal_index, identity[1])
        batch = []
        for row in source_rows:
            signal_ms = int(row["signal_ms"])
            shape = shape_by_identity.get((signal_ms, str(row["direction"])))
            eligible = [
                int(resolvers[threshold].membership_at(symbol, signal_ms) is not None)
                for threshold in THRESHOLDS
            ]
            mfe = row["mfe_960_r"]
            batch.append(
                (
                    str(row["family_id"]),
                    symbol,
                    signal_ms,
                    str(row["direction"]),
                    shape["relative_quote_volume"] if shape else None,
                    *(int(shape["breaks_channel"][str(channel)]) if shape else None for channel in CHANNELS),
                    *eligible,
                    None if mfe is None else int(float(mfe) >= 10.0),
                )
            )
        target.executemany("insert into events values(?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        target.execute("insert into processed_symbols values(?)", (symbol,))
        target.commit()
        if offset % 25 == 0 or offset == len(symbols):
            print(f"processed {offset}/{len(symbols)} symbols: {symbol}", flush=True)


def _build_report(connection, resolvers, contracts, spec):
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute("select * from events")]
    if len(rows) != int(spec["source_event_count"]):
        raise RuntimeError(f"incomplete RC-0B feature database: {len(rows)}")
    start_day_ms = min(int(row["signal_time_ms"]) for row in rows) // DAY_MS * DAY_MS
    end_day_ms = int(spec["training_end_ms"]) // DAY_MS * DAY_MS
    universe = _universe_summaries(resolvers, contracts, start_day_ms, end_day_ms)
    families = []
    for family_id in ("BREAKOUT_MOMENTUM", "OVERSOLD_REBOUND"):
        source_rows = [row for row in rows if row["family_id"] == family_id]
        combinations = []
        shape_options = (
            [(channel, relative_volume) for channel in CHANNELS for relative_volume in RELATIVE_VOLUMES]
            if family_id == "BREAKOUT_MOMENTUM"
            else [(None, None)]
        )
        for threshold in THRESHOLDS:
            for channel, relative_volume in shape_options:
                selected = select_combination(
                    source_rows,
                    liquidity_threshold_usdt=threshold,
                    channel_lookback_candles=channel,
                    minimum_relative_quote_volume=relative_volume,
                )
                combinations.append(
                    {
                        "liquidity_threshold_usdt": threshold,
                        "channel_lookback_candles": channel,
                        "minimum_relative_quote_volume": relative_volume,
                        "frequency": _compact_frequency_summary(
                            selected, start_day_ms=start_day_ms, end_day_ms=end_day_ms
                        ),
                        "retained_signal_fraction": len(selected) / len(source_rows),
                        "large_opportunity_reference": large_opportunity_retention(source_rows, selected),
                        "simultaneously_eligible_markets": universe[str(threshold)]["distribution"],
                    }
                )
        families.append(
            {
                "family_id": family_id,
                "source_event_count": len(source_rows),
                "source_frequency": _compact_frequency_summary(
                    source_rows, start_day_ms=start_day_ms, end_day_ms=end_day_ms
                ),
                "combinations": combinations,
            }
        )
    return {
        "protocol": "ORBIT_RC0B_VOLUME_CURVE_REPORT_V1",
        "contract_sha256": _sha256(SPEC_PATH),
        "source_rc0_report_sha256": _sha256(SOURCE_REPORT_PATH),
        "dataset_fingerprint": spec["dataset_fingerprint"],
        "training_end_ms": int(spec["training_end_ms"]),
        "measurement_start_day_ms": start_day_ms,
        "measurement_end_day_ms": end_day_ms,
        "source_event_count": len(rows),
        "lockbox_opened": False,
        "lockbox_data_read": False,
        "predictive_filter_added": False,
        "selection_or_gate_effect": "NONE",
        "user_selection_required": True,
        "universe_by_liquidity_threshold": universe,
        "family_reports": families,
        "honesty_boundary": [
            "THIS_REPORT_MEASURES_SIGNAL_VOLUME_NOT_PREDICTIVE_QUALITY",
            "MFE_10R_IS_A_FUTURE_PATH_LABEL_USED_ONLY_TO_DESCRIBE_REDUCTION_COST",
            "ALL_COUNTS_ARE_FROM_THE_FROZEN_TRAINING_PERIOD",
            "NO_COMBINATION_IS_SELECTED_BY_THIS_REPORT",
            "NO_LOCKBOX_DATA_READ",
        ],
    }


def _compact_frequency_summary(events, *, start_day_ms, end_day_ms):
    summary = frequency_summary(events, start_day_ms=start_day_ms, end_day_ms=end_day_ms)
    daily_counts = list(summary.pop("by_day").values())
    summary["daily_signal_count_distribution"] = distribution_summary(daily_counts)
    return summary


def _universe_summaries(resolvers, contracts, start_day_ms, end_day_ms):
    result = {}
    symbols = [str(item["symbol"]) for item in contracts]
    for threshold in THRESHOLDS:
        by_day = {}
        resolver = resolvers[threshold]
        for timestamp in range(start_day_ms, end_day_ms + 1, DAY_MS):
            key = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            by_day[key] = sum(resolver.membership_at(symbol, timestamp) is not None for symbol in symbols)
        result[str(threshold)] = {
            "distribution": distribution_summary(list(by_day.values())),
            "by_day": by_day,
        }
    return result


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# RC-0B：币池门槛 × 形态严格度降量曲线",
        "",
        "本报告只回答‘每天/月需要看多少个信号，以及会漏掉多少训练期大机会’，不评价预测能力，也不替用户选择组合。",
        "",
        "## 结果表",
        "",
        "| 信号族 | 日成交额门槛 | 通道 | 放量 | 日均 | 月均 | 月p90 | 单日最大 | 单月最大 | 信号保留 | 10天≥10R保留 | 同时合格市场日均 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for family in report["family_reports"]:
        family_name = "突破" if family["family_id"] == "BREAKOUT_MOMENTUM" else "超跌"
        for item in family["combinations"]:
            frequency = item["frequency"]
            large = item["large_opportunity_reference"]["retained_large_opportunity_fraction"]
            lines.append(
                "| {family} | {threshold} | {channel} | {volume} | {daily:.1f} | {monthly:.1f} | "
                "{p90:.1f} | {day_max} | {month_max} | {retained:.1%} | {large_text} | {markets:.1f} |".format(
                    family=family_name,
                    threshold=_threshold_label(item["liquidity_threshold_usdt"]),
                    channel=item["channel_lookback_candles"] or "冻结",
                    volume=item["minimum_relative_quote_volume"] or "冻结",
                    daily=frequency["mean_signals_per_day"],
                    monthly=frequency["mean_signals_per_month"],
                    p90=frequency["monthly_p90"],
                    day_max=frequency["maximum_signals_per_day"],
                    month_max=frequency["maximum_signals_per_month"],
                    retained=item["retained_signal_fraction"],
                    large_text=f"{large:.1%}" if large is not None else "无标签",
                    markets=item["simultaneously_eligible_markets"]["mean"],
                )
            )
    lines.extend(
        [
            "",
            "## 如何读表",
            "",
            "- 日均、月均、月 p90 和峰值衡量人工工作量；均值低不代表共振日没有洪峰。",
            "- 信号保留是相对各信号族 RC-0 全量母池的比例。",
            "- 10天≥10R保留只描述降量代价。它使用未来路径标签，不能在线计算，也不是选择依据。",
            "- 同时合格市场数采用信号时刻一致的前 3 个完整 UTC 日成交额中位数口径；少于 3 个市场时按冻结规则记为 0。",
            "- 所有数字均来自截至 2024-12-31 的训练期。锁箱未打开、未读取。最终组合必须由用户依据真实工作量选择。",
            "",
        ]
    )
    return "\n".join(lines)


def _threshold_label(value: int) -> str:
    return {30_000_000: "3000万", 100_000_000: "1亿", 200_000_000: "2亿", 500_000_000: "5亿"}[value]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_lf_exclusive(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(content)


def _write_text_lf_exclusive(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as target:
        target.write(content.encode("utf-8"))


if __name__ == "__main__":
    main()
