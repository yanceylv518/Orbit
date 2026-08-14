"""Generate the RB-2 joint MFE/MAE and early-adverse-path diagnostic."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.rb1_oversold import verify_context  # noqa: E402
from orbit.application.rb2_joint_path import MFE_BUCKETS, joint_bucket_summary  # noqa: E402
from orbit.application.rb2_long_cycle import future_extrema, path_metrics  # noqa: E402
from screen_r0_shortline import _market_loader, _prepare_universe  # noqa: E402

ROOT = PROJECT_ROOT / "var/calibration/shortline-data-v1"
CHECKPOINTS = PROJECT_ROOT / "var/research/r0-diag2-reproduction-checkpoints"
SPEC_PATH = PROJECT_ROOT / "config/research/rb2_joint_path.v1.json"
RB1_PATH = PROJECT_ROOT / "config/research/rb1_oversold.v1.json"
R0_PATH = PROJECT_ROOT / "config/research/r0_shortline_screen.v2.json"
BASELINE_PATH = PROJECT_ROOT / "docs/evidence/r0/r0_training_v2_20260812.json"
SOURCE_REPORT_PATH = PROJECT_ROOT / "docs/evidence/rb2/rb2_long_cycle_v3_20260814.json"
EARLY_WINDOWS = (4, 8, 16, 32)
HORIZONS = (96, 288, 960)

SCHEMA = """
create table events(
  parameter_id text not null,
  family_id text not null,
  symbol text not null,
  signal_ms integer not null,
  atr_relative_pct real not null,
  early_mae_4_r real,
  early_mae_8_r real,
  early_mae_16_r real,
  early_mae_32_r real,
  mfe_96_r real, mae_96_r real, mfe_96_bar integer, mae_96_bar integer,
  mfe_288_r real, mae_288_r real, mfe_288_bar integer, mae_288_bar integer,
  mfe_960_r real, mae_960_r real, mfe_960_bar integer, mae_960_bar integer
);
create table processed_symbols(symbol text primary key);
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--summarize-existing", action="store_true")
    args = parser.parse_args()

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    training_end_ms = int(spec["training_end_ms"])
    if training_end_ms >= int(spec["lockbox_start_ms"]):
        raise RuntimeError("training boundary reaches lockbox")
    if spec["discipline"]["lockbox_access"] != "PROHIBITED":
        raise RuntimeError("lockbox access is not prohibited")
    if _sha256(SOURCE_REPORT_PATH) != spec["source_report_sha256"]:
        raise RuntimeError("source v3 report hash mismatch")

    context = verify_context(RB1_PATH, R0_PATH, ROOT)
    if context["manifest"]["dataset_fingerprint"] != spec["dataset_fingerprint"]:
        raise RuntimeError("dataset fingerprint mismatch")
    symbols, _ = _prepare_universe(ROOT, context["contract"], maximum_time_ms=training_end_ms)
    loader = _market_loader(ROOT, minimum_time_ms=None, maximum_time_ms=training_end_ms)
    selected = _selected_parameters()

    database_path = Path(args.db)
    connection = _open_database(database_path, resume=args.resume or args.summarize_existing)
    if not args.summarize_existing:
        _scan(connection, symbols, selected, loader)
    _ensure_indexes(connection)
    report = _build_report(connection, spec, context, selected)
    _write_json_lf_exclusive(Path(args.out), report)
    connection.close()
    print(json.dumps({"output": args.out, "events": report["event_count_total"], "parameters": len(selected)}))


def _selected_parameters() -> dict[str, dict[str, Any]]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    selected = [
        item
        for item in baseline["parameter_reports"]
        if item["definition_id"] == "B1_DONCHIAN_VOLUME"
        or (
            item["definition_id"] == "S1_DROP_STABILIZATION"
            and item["parameters"]["minimum_drop_fraction"] == "0.10"
        )
    ]
    if len(selected) != 12:
        raise RuntimeError(f"expected 12 frozen parameters, got {len(selected)}")
    return {item["parameter_id"]: item for item in selected}


def _open_database(path: Path, *, resume: bool) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    if resume:
        if not path.exists():
            raise RuntimeError("joint-path sqlite does not exist")
        connection = sqlite3.connect(path)
    else:
        if path.exists():
            raise RuntimeError("joint-path sqlite already exists")
        connection = sqlite3.connect(path)
        connection.executescript(SCHEMA)
    connection.execute("pragma journal_mode=wal")
    connection.execute("pragma synchronous=normal")
    return connection


def _scan(connection, symbols, selected, loader) -> None:
    completed = {row[0] for row in connection.execute("select symbol from processed_symbols")}
    for symbol in sorted(symbols):
        if symbol in completed:
            continue
        checkpoint_path = CHECKPOINTS / f"{symbol}.json"
        if not checkpoint_path.exists():
            raise RuntimeError(f"missing frozen checkpoint: {symbol}")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        chosen = []
        for parameter_id, parameter in selected.items():
            index = checkpoint["parameter_ids"].index(parameter_id)
            events = checkpoint["event_sets"][index]
            if events:
                chosen.append((parameter_id, parameter["family_id"], events))
        if not chosen:
            connection.execute("insert into processed_symbols values(?)", (symbol,))
            connection.commit()
            continue

        candles, _ = loader(symbol)
        open_indexes = {row.open_time_ms: index for index, row in enumerate(candles)}
        extrema = {window: future_extrema(candles, window) for window in (*EARLY_WINDOWS, *HORIZONS)}
        batch = []
        for parameter_id, family_id, events in chosen:
            for event in events:
                entry_index = open_indexes[int(event["entry_time_ms"])]
                entry_price = float(event["entry_price"])
                initial_r = 2 * float(event["atr14"])
                direction = event["direction"]
                early = {
                    window: path_metrics(
                        candles, entry_index, direction, entry_price, initial_r, window, extrema[window]
                    )
                    for window in EARLY_WINDOWS
                }
                long_path = {
                    horizon: path_metrics(
                        candles, entry_index, direction, entry_price, initial_r, horizon, extrema[horizon]
                    )
                    for horizon in HORIZONS
                }
                batch.append(
                    (
                        parameter_id,
                        family_id,
                        symbol,
                        int(event["signal_time_ms"]),
                        float(event["atr14"]) / entry_price * 100,
                        *(early[window]["mae_r"] if early[window] else None for window in EARLY_WINDOWS),
                        *(
                            value
                            for horizon in HORIZONS
                            for value in (
                                long_path[horizon]["mfe_r"] if long_path[horizon] else None,
                                long_path[horizon]["mae_r"] if long_path[horizon] else None,
                                long_path[horizon]["mfe_bar"] if long_path[horizon] else None,
                                long_path[horizon]["mae_bar"] if long_path[horizon] else None,
                            )
                        ),
                    )
                )
        connection.executemany("insert into events values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        connection.execute("insert into processed_symbols values(?)", (symbol,))
        connection.commit()


def _ensure_indexes(connection) -> None:
    connection.execute("create index if not exists events_parameter on events(parameter_id)")
    connection.execute("create index if not exists events_family on events(family_id)")
    connection.commit()


def _build_report(connection, spec, context, selected) -> dict[str, Any]:
    family_reports = [
        _scope_report(connection, "family_id", family_id, family_id, None)
        for family_id in ("BREAKOUT_MOMENTUM", "OVERSOLD_REBOUND")
    ]
    parameter_reports = [
        _scope_report(
            connection,
            "parameter_id",
            parameter_id,
            parameter["family_id"],
            parameter["parameters"],
        )
        for parameter_id, parameter in selected.items()
    ]
    event_count_total, symbol_count = connection.execute(
        "select count(*),count(distinct symbol) from events"
    ).fetchone()
    return {
        "protocol": "ORBIT_RB2_JOINT_PATH_REPORT_V1",
        "contract_sha256": _sha256(SPEC_PATH),
        "source_report_sha256": _sha256(SOURCE_REPORT_PATH),
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "training_end_ms": int(spec["training_end_ms"]),
        "lockbox_opened": False,
        "lockbox_data_read": False,
        "selection_or_gate_effect": "NONE",
        "event_count_total": event_count_total,
        "symbol_count": symbol_count,
        "horizons_candles": list(HORIZONS),
        "mfe_buckets_r": list(MFE_BUCKETS),
        "early_adverse_windows_candles": list(EARLY_WINDOWS),
        "risk_conversion": spec["risk_conversion"],
        "timing_relation": spec["timing_relation"],
        "family_reports": family_reports,
        "parameter_reports": parameter_reports,
        "honesty_boundary": [
            "JOINT_PATHS_ARE_HINDSIGHT_DIAGNOSTICS_NOT_EXECUTED_RETURNS",
            "EARLY_ADVERSE_DIFFERENCES_REQUIRE_INDEPENDENT_FORWARD_VALIDATION",
            "NO_NEW_FILTER_OR_EXIT_RULE_IS_CREATED",
            "NO_LOCKBOX_DATA_READ",
        ],
    }


def _scope_report(connection, column, value, family_id, parameters) -> dict[str, Any]:
    report = {"scope_id": value, "family_id": family_id, "horizons": {}}
    if parameters is not None:
        report["parameters"] = parameters
    for horizon in HORIZONS:
        report["horizons"][str(horizon)] = {
            bucket: joint_bucket_summary(_bucket_rows(connection, column, value, horizon, bucket))
            for bucket in MFE_BUCKETS
        }
    return report


def _bucket_rows(connection, column, value, horizon, bucket):
    conditions = {
        "LT_2R": f"mfe_{horizon}_r < 2",
        "GTE_2_LT_5R": f"mfe_{horizon}_r >= 2 and mfe_{horizon}_r < 5",
        "GTE_5_LT_10R": f"mfe_{horizon}_r >= 5 and mfe_{horizon}_r < 10",
        "GTE_10R": f"mfe_{horizon}_r >= 10",
    }
    early_columns = ",".join(
        f"early_mae_{window}_r,early_mae_{window}_r*2*atr_relative_pct as early_mae_{window}_entry_price_pct"
        for window in EARLY_WINDOWS
    )
    query = f"""
        select mfe_{horizon}_r as mfe_r,
               mae_{horizon}_r as mae_r,
               mae_{horizon}_r*2*atr_relative_pct as mae_entry_price_pct,
               mfe_{horizon}_bar as mfe_bar,
               mae_{horizon}_bar as mae_bar,
               {early_columns}
          from events
         where {column}=? and mfe_{horizon}_r is not null and {conditions[bucket]}
    """
    connection.row_factory = sqlite3.Row
    return list(connection.execute(query, (value,)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_lf_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with path.open("xb") as target:
        target.write(content)


if __name__ == "__main__":
    main()
