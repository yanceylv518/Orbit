"""Generate the RC-0 range-reduction funnel diagnostic."""
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
from orbit.application.rb2_long_cycle import future_extrema, path_metrics  # noqa: E402
from orbit.application.rc0_funnel import FILTERS, funnel_curve, signal_features  # noqa: E402
from screen_r0_shortline import _market_loader, _prepare_universe  # noqa: E402

ROOT = PROJECT_ROOT / "var/calibration/shortline-data-v1"
CHECKPOINTS = PROJECT_ROOT / "var/research/r0-diag2-reproduction-checkpoints"
SPEC_PATH = PROJECT_ROOT / "config/research/rc0_funnel.v1.json"
RB1_PATH = PROJECT_ROOT / "config/research/rb1_oversold.v1.json"
R0_PATH = PROJECT_ROOT / "config/research/r0_shortline_screen.v2.json"
BASELINE_PATH = PROJECT_ROOT / "docs/evidence/r0/r0_training_v2_20260812.json"
SOURCE_REPORT_PATH = PROJECT_ROOT / "docs/evidence/rb2/rb2_joint_path_v4_20260814.json"
FEATURE_WINDOWS = (96, 288)
OUTCOME_HORIZONS = (96, 288, 960)

SCHEMA = """
create table events(
  family_id text not null,
  symbol text not null,
  signal_ms integer not null,
  direction text not null,
  efficiency_ratio_96 real,
  trend_strength_96 real,
  wickiness_96 real,
  efficiency_ratio_288 real,
  trend_strength_288 real,
  wickiness_288 real,
  mfe_96_r real,
  mfe_288_r real,
  mfe_960_r real,
  primary key(family_id,symbol,signal_ms,direction)
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
    if _sha256(SOURCE_REPORT_PATH) != spec["source_joint_report_sha256"]:
        raise RuntimeError("source joint-path report hash mismatch")

    context = verify_context(RB1_PATH, R0_PATH, ROOT)
    if context["manifest"]["dataset_fingerprint"] != spec["dataset_fingerprint"]:
        raise RuntimeError("dataset fingerprint mismatch")
    symbols, _ = _prepare_universe(ROOT, context["contract"], maximum_time_ms=training_end_ms)
    loader = _market_loader(ROOT, minimum_time_ms=None, maximum_time_ms=training_end_ms)
    selected = _selected_parameters()
    connection = _open_database(Path(args.db), resume=args.resume or args.summarize_existing)
    if not args.summarize_existing:
        _scan(connection, symbols, selected, loader)
    report = _build_report(connection, spec, context)
    _write_json_lf_exclusive(Path(args.out), report)
    connection.close()
    print(json.dumps({"output": args.out, "events": report["deduplicated_event_count"]}))


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
            raise RuntimeError("RC-0 sqlite does not exist")
        connection = sqlite3.connect(path)
    else:
        if path.exists():
            raise RuntimeError("RC-0 sqlite already exists")
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
        unique_events = {}
        for parameter_id, parameter in selected.items():
            parameter_index = checkpoint["parameter_ids"].index(parameter_id)
            for event in checkpoint["event_sets"][parameter_index]:
                identity = (parameter["family_id"], symbol, int(event["signal_time_ms"]), event["direction"])
                fingerprint = (
                    int(event["entry_time_ms"]),
                    float(event["entry_price"]),
                    float(event["atr14"]),
                )
                if identity in unique_events and unique_events[identity][0] != fingerprint:
                    raise RuntimeError(f"deduplicated event mismatch: {identity}")
                unique_events[identity] = (fingerprint, event)
        if not unique_events:
            connection.execute("insert into processed_symbols values(?)", (symbol,))
            connection.commit()
            continue

        candles, _ = loader(symbol)
        close_indexes = {row.close_time_ms: index for index, row in enumerate(candles)}
        open_indexes = {row.open_time_ms: index for index, row in enumerate(candles)}
        extrema = {horizon: future_extrema(candles, horizon) for horizon in OUTCOME_HORIZONS}
        batch = []
        for identity, (_, event) in sorted(unique_events.items()):
            family_id, _, signal_ms, direction = identity
            signal_index = close_indexes[signal_ms]
            entry_index = open_indexes[int(event["entry_time_ms"])]
            atr14 = float(event["atr14"])
            entry_price = float(event["entry_price"])
            features = {
                window: signal_features(candles, signal_index, direction, atr14, window)
                for window in FEATURE_WINDOWS
            }
            paths = {
                horizon: path_metrics(
                    candles,
                    entry_index,
                    direction,
                    entry_price,
                    2 * atr14,
                    horizon,
                    extrema[horizon],
                )
                for horizon in OUTCOME_HORIZONS
            }
            batch.append(
                (
                    family_id,
                    symbol,
                    signal_ms,
                    direction,
                    *(
                        value
                        for window in FEATURE_WINDOWS
                        for value in (
                            features[window]["efficiency_ratio"] if features[window] else None,
                            features[window]["trend_strength"] if features[window] else None,
                            features[window]["wickiness"] if features[window] else None,
                        )
                    ),
                    *(paths[horizon]["mfe_r"] if paths[horizon] else None for horizon in OUTCOME_HORIZONS),
                )
            )
        connection.executemany("insert into events values(?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        connection.execute("insert into processed_symbols values(?)", (symbol,))
        connection.commit()


def _build_report(connection, spec, context) -> dict[str, Any]:
    retained_fractions = [float(value) for value in spec["retained_fraction_scan"]]
    workload = spec["usable_workload_mean_signals_per_month"]
    family_reports = []
    for family_id in spec["families"]:
        feature_windows = {}
        for feature_window in FEATURE_WINDOWS:
            outcomes = {}
            for outcome_horizon in OUTCOME_HORIZONS:
                events = _load_events(connection, family_id, feature_window, outcome_horizon)
                outcomes[str(outcome_horizon)] = {
                    "is_primary_large_opportunity_horizon": outcome_horizon
                    == int(spec["primary_large_opportunity"]["horizon_candles"]),
                    "eligible_event_count": len(events),
                    "filters": {
                        filter_name: funnel_curve(
                            events,
                            filter_name,
                            retained_fractions,
                            workload_minimum=float(workload["minimum"]),
                            workload_maximum=float(workload["maximum"]),
                        )
                        for filter_name in FILTERS
                    },
                }
            feature_windows[str(feature_window)] = {"outcome_horizons": outcomes}
        family_reports.append(
            {
                "family_id": family_id,
                "deduplicated_event_count": connection.execute(
                    "select count(*) from events where family_id=?", (family_id,)
                ).fetchone()[0],
                "feature_windows": feature_windows,
            }
        )
    return {
        "protocol": "ORBIT_RC0_FUNNEL_REPORT_V1",
        "contract_sha256": _sha256(SPEC_PATH),
        "source_joint_report_sha256": _sha256(SOURCE_REPORT_PATH),
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "training_end_ms": int(spec["training_end_ms"]),
        "lockbox_opened": False,
        "lockbox_data_read": False,
        "selection_or_gate_effect": "NONE",
        "deduplication_identity": spec["event_identity"],
        "deduplicated_event_count": connection.execute("select count(*) from events").fetchone()[0],
        "primary_large_opportunity": spec["primary_large_opportunity"],
        "companion_outcome_horizons_candles": list(OUTCOME_HORIZONS),
        "feature_windows_candles": list(FEATURE_WINDOWS),
        "filters": spec["filters"],
        "family_reports": family_reports,
        "honesty_boundary": [
            "MFE_LABELS_USE_FUTURE_PATHS_AND_ARE_NOT_AVAILABLE_ONLINE",
            "ALL_BOUNDARIES_ARE_TRAINING_EXPLORATION",
            "ENRICHMENT_REQUIRES_INDEPENDENT_FORWARD_VALIDATION",
            "NO_FILTER_OR_TRADING_RULE_IS_CREATED",
            "NO_LOCKBOX_DATA_READ",
        ],
    }


def _load_events(connection, family_id, feature_window, outcome_horizon):
    query = f"""
        select family_id,symbol,signal_ms as signal_time_ms,direction,
               efficiency_ratio_{feature_window} as efficiency_ratio,
               trend_strength_{feature_window} as trend_strength,
               wickiness_{feature_window} as wickiness,
               case when mfe_{outcome_horizon}_r >= 10 then 1 else 0 end as large_opportunity
          from events
         where family_id=?
           and efficiency_ratio_{feature_window} is not null
           and trend_strength_{feature_window} is not null
           and wickiness_{feature_window} is not null
           and mfe_{outcome_horizon}_r is not null
    """
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query, (family_id,))]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_lf_exclusive(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    with path.open("xb") as target:
        target.write(content)


if __name__ == "__main__":
    main()
