"""Append frozen R-0 breakout opportunity profiles without reading market archives."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.rb2_opportunity_profile import profile_events  # noqa: E402

CHECKPOINTS = PROJECT_ROOT / "var/research/r0-diag2-reproduction-checkpoints"
BASELINE = PROJECT_ROOT / "docs/evidence/r0/r0_training_v2_20260812.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report_path = Path(args.report)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("lockbox_data_read") or report.get("lockbox_opened"):
        raise RuntimeError("RB-2 lockbox invariant changed")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    baseline_rows = [row for row in baseline["parameter_reports"] if row["definition_id"] == "B1_DONCHIAN_VOLUME"]
    existing = [row for row in report["profiles"] if row.get("family_id") != "BREAKOUT_MOMENTUM"]
    for row in existing:
        row["family_id"] = "OVERSOLD_REBOUND"
    breakout = []
    for parameter in baseline_rows:
        events = []
        parameter_id = parameter["parameter_id"]
        for path in CHECKPOINTS.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            index = payload["parameter_ids"].index(parameter_id)
            events.extend(payload["event_sets"][index])
        expected = parameter["summary"]
        mean = sum(float(row["net_return_pct"]) for row in events) / len(events)
        if len(events) != int(expected["event_count"]) or abs(mean - float(expected["mean_net_return_pct"])) > 1e-12:
            raise RuntimeError("breakout frozen event reproduction mismatch")
        for row in events:
            initial_r = 2 * float(row["atr14"])
            row["initial_r"] = initial_r
            row["final_return_r"] = (float(row["net_return_pct"]) / 100 * float(row["entry_price"])) / initial_r
            # R-0 checkpoints do not contain paths. MFE/R is intentionally null here;
            # all remaining profile groups use the complete frozen event population.
            row["mfe_r"] = 0.0
            row["features"] = {
                "drop_depth_pct": None, "relative_quote_volume": None,
                "volume_trend_3d": row["volume_trend_3d"],
                "btc_same_window_return_pct": None, "tier": row["tier"],
                "utc_hour": int(row["entry_time_ms"] // 3_600_000 % 24),
                "listing_age": row["listing_age"], "atr_relative_pct": float(row["atr14"]) / float(row["entry_price"]) * 100,
            }
        profile = profile_events(events)
        profile["r_multiple_distribution"]["mfe_unavailable_reason"] = "FROZEN_R0_CHECKPOINT_HAS_NO_PATH_CANDLES;NOT_FABRICATED"
        profile["r_multiple_distribution"]["mfe_r_quantiles"] = None
        profile["r_multiple_distribution"]["mfe_touch_rate"] = None
        profile["r_multiple_distribution"]["mfe_r_histogram"] = None
        breakout.append({"family_id": "BREAKOUT_MOMENTUM", "parameter_id": parameter_id, "parameters": parameter["parameters"], "exit_profile": "R0_FIXED_EXIT_2_ATR_STOP", "signal_identity": {"event_count": len(events), "matches_frozen_r0": True}, "profile": profile})
    report["profiles"] = existing + breakout
    report["profile_count_by_family"] = {"OVERSOLD_REBOUND": len(existing), "BREAKOUT_MOMENTUM": len(breakout)}
    temporary = report_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(report_path)
    print(json.dumps(report["profile_count_by_family"], ensure_ascii=False))


if __name__ == "__main__": main()
