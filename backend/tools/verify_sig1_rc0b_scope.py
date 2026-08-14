"""Verify SIG-1 scope reference and p90 thresholds against RC-0B evidence.

RC-0B counts come from its frozen, position-suppressed research event pool.
SIG-1 scans every completed candle and allows overlapping virtual trades, so
these counts are calibration references rather than claims about raw runtime
replay totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = PROJECT_ROOT / "config/signals/sig1.v1.json"
REPORT_PATH = PROJECT_ROOT / "docs/evidence/rc0/rc0b_volume_curve_v1_20260814.json"
RC0_DB = PROJECT_ROOT / "var/research/rc0-funnel-v1.sqlite"
RC0B_DB = PROJECT_ROOT / "var/research/rc0b-volume-curve-v1.sqlite"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out")
    parser.add_argument("--rc0-db", default=str(RC0_DB))
    parser.add_argument("--rc0b-db", default=str(RC0B_DB))
    args = parser.parse_args()
    payload = verify(Path(args.rc0_db), Path(args.rc0b_db))
    content = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as target:
            target.write(content)
    else:
        print(content, end="")


def verify(rc0_db: Path, rc0b_db: Path):
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    report_hash = hashlib.sha256(REPORT_PATH.read_bytes()).hexdigest()
    if report_hash != spec["source_rc0b_report_sha256"]:
        raise RuntimeError("SIG-1 source RC-0B report hash mismatch")
    if spec["event_stream_source"] != "EVERY_COMPLETED_15M_CANDLE":
        raise RuntimeError("SIG-1 runtime event source has drifted")
    reference = spec["historical_reference"]
    if reference["source"] != "RC0B_DEDUPLICATED_RESEARCH_EVENT_POOL":
        raise RuntimeError("SIG-1 historical reference has drifted")
    if reference["runtime_reuses_research_position_suppression"]:
        raise RuntimeError("SIG-1 must not reuse the RC-0B position-suppression gate")
    families = {row["family_id"]: row for row in report["family_reports"]}
    breakout_report = next(
        row for row in families["BREAKOUT_MOMENTUM"]["combinations"]
        if row["liquidity_threshold_usdt"] == 200_000_000
        and row["channel_lookback_candles"] == 32
        and row["minimum_relative_quote_volume"] == 4.0
    )
    oversold_report = next(
        row for row in families["OVERSOLD_REBOUND"]["combinations"]
        if row["liquidity_threshold_usdt"] == 200_000_000
    )
    connection = sqlite3.connect(rc0_db)
    connection.execute("attach database ? as rc0b", (str(rc0b_db),))
    reference_counts = {
        "BREAKOUT_MOMENTUM": connection.execute(
            "select count(*) from rc0b.events where family_id='BREAKOUT_MOMENTUM' "
            "and eligible_200000000=1 and breaks_channel_32=1 and relative_quote_volume>=4.0"
        ).fetchone()[0],
        "OVERSOLD_REBOUND": connection.execute(
            "select count(*) from rc0b.events where family_id='OVERSOLD_REBOUND' "
            "and eligible_200000000=1"
        ).fetchone()[0],
    }
    expected_counts = {
        "BREAKOUT_MOMENTUM": int(breakout_report["frequency"]["event_count"]),
        "OVERSOLD_REBOUND": int(oversold_report["frequency"]["event_count"]),
    }
    if reference_counts != expected_counts:
        raise RuntimeError(
            f"SIG-1 RC-0B reference mismatch: {reference_counts} != {expected_counts}"
        )
    thresholds = {}
    for family_id in reference_counts:
        values = [
            float(row[0])
            for row in connection.execute(
                "select source.trend_strength_96 from events source join rc0b.events selected "
                "on source.family_id=selected.family_id and source.symbol=selected.symbol "
                "and source.signal_ms=selected.signal_time_ms and source.direction=selected.direction "
                "where selected.eligible_200000000=1 and source.family_id=? "
                "and ((source.family_id='BREAKOUT_MOMENTUM' and selected.breaks_channel_32=1 "
                "and selected.relative_quote_volume>=4.0) or source.family_id='OVERSOLD_REBOUND') "
                "and source.trend_strength_96 is not null order by source.trend_strength_96",
                (family_id,),
            )
        ]
        thresholds[family_id] = _quantile(values, 0.90)
        frozen = float(spec["notifications"]["trend_strength_minimum_by_family"][family_id])
        if thresholds[family_id] != frozen:
            raise RuntimeError(f"SIG-1 {family_id} p90 mismatch: {thresholds[family_id]} != {frozen}")
    connection.close()
    return {
        "protocol": "ORBIT_SIG1_RC0B_SCOPE_REFERENCE_V1",
        "sig1_spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "source_rc0b_report_sha256": report_hash,
        "lockbox_opened": False,
        "lockbox_data_read": False,
        "runtime_event_stream_source": spec["event_stream_source"],
        "runtime_reuses_research_position_suppression": False,
        "rc0b_reference_event_counts": reference_counts,
        "expected_rc0b_reference_event_counts": expected_counts,
        "trend_strength_96_family_p90": thresholds,
        "reference_count_match": True,
        "threshold_match": True,
    }


def _quantile(values, level):
    position = (len(values) - 1) * level
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


if __name__ == "__main__":
    main()
