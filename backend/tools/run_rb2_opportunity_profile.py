"""Build the descriptive RB-2 opportunity profile from training data only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.rb1_oversold import verify_context as verify_rb1_context  # noqa: E402
from orbit.application.rb2_opportunity_profile import add_opportunity_metrics, observable_features, profile_events  # noqa: E402
from orbit.domain.calibration.rb1_oversold import simulate_candidate_events  # noqa: E402
from screen_r0_shortline import _market_loader, _prepare_universe, _write_exclusive  # noqa: E402

RB2_SPEC = PROJECT_ROOT / "config" / "research" / "rb2_opportunity_profile.v1.json"
RB1_SPEC = PROJECT_ROOT / "config" / "research" / "rb1_oversold.v1.json"
R0_SPEC = PROJECT_ROOT / "config" / "research" / "r0_shortline_screen.v2.json"
ROOT = PROJECT_ROOT / "var" / "calibration" / "shortline-data-v1"
R0_CHECKPOINTS = PROJECT_ROOT / "var" / "research" / "r0-diag2-reproduction-checkpoints"
R0_REPORT = PROJECT_ROOT / "docs" / "evidence" / "r0" / "r0_training_v2_20260812.json"
PARAMETER_IDS = {
    "S1_DROP_STABILIZATION:b5b337dfcf2d": (16, 8, 10),
    "S1_DROP_STABILIZATION:32b74c44f05b": (16, 16, 11),
    "S1_DROP_STABILIZATION:f48a63c80597": (32, 8, 14),
    "S1_DROP_STABILIZATION:3bcc4091c77b": (32, 16, 15),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    spec_raw = RB2_SPEC.read_bytes()
    spec = json.loads(spec_raw)
    if spec["discipline"]["lockbox_access"] != "PROHIBITED" or spec["training_end_ms"] >= spec["lockbox_start_ms"]:
        raise RuntimeError("RB-2 lockbox boundary is invalid")
    context = verify_rb1_context(RB1_SPEC, R0_SPEC, ROOT)
    if spec["dataset_fingerprint"] != context["manifest"]["dataset_fingerprint"]:
        raise RuntimeError("RB-2 dataset identity mismatch")
    end_ms = int(spec["training_end_ms"])
    symbols, resolver = _prepare_universe(ROOT, context["contract"], maximum_time_ms=end_ms)
    loader = _market_loader(ROOT, minimum_time_ms=None, maximum_time_ms=end_ms)
    btc_candles, _ = loader("BTCUSDT")
    btc_by_time = {row.close_time_ms: index for index, row in enumerate(btc_candles)}
    costs = {str(item["tier"]): float(item["round_trip"]) for item in context["contract"]["execution"]["costs_pct_per_side_by_tier"]}
    r0_baseline = json.loads(R0_REPORT.read_text(encoding="utf-8"))
    baseline_by_id = {row["parameter_id"]: row for row in r0_baseline["parameter_reports"]}
    profiles = []
    for parameter_id, (lookback, holding, checkpoint_index) in PARAMETER_IDS.items():
        r0_rows, rb1_rows = [], []
        for symbol in sorted(symbols):
            checkpoint = R0_CHECKPOINTS / f"{symbol}.json"
            if not checkpoint.exists():
                raise RuntimeError(f"missing frozen R-0 checkpoint: {symbol}")
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            if payload["parameter_ids"][checkpoint_index] != parameter_id:
                raise RuntimeError("R-0 checkpoint parameter order changed")
            frozen_events = payload["event_sets"][checkpoint_index]
            if not frozen_events:
                continue
            candles, funding = loader(symbol)
            index_by_signal = {row.close_time_ms: index for index, row in enumerate(candles)}
            signal_indices = [
                index_by_signal[int(event["signal_time_ms"])]
                for event in frozen_events
                if index_by_signal[int(event["signal_time_ms"])] + 33 < len(candles)
                and candles[index_by_signal[int(event["signal_time_ms"])] + 33].open_time_ms <= end_ms
            ]
            rb1_events = simulate_candidate_events(symbol, candles, funding, signal_indices, "ST-B__EX-B", tier_at=resolver.tier_at, costs=costs, end_ms=end_ms, diagnostics_at=resolver.diagnostics_at)
            rb1_by_signal = {int(x["signal_time_ms"]): x for x in rb1_events}
            comparable = [(original, index_by_signal[int(original["signal_time_ms"])]) for original in frozen_events if int(original["signal_time_ms"]) in rb1_by_signal]
            for original, signal_index in comparable:
                modified = rb1_by_signal[int(original["signal_time_ms"])]
                btc_index = btc_by_time.get(int(original["signal_time_ms"]))
                btc_return = None if btc_index is None or btc_index < lookback else (btc_candles[btc_index].close / btc_candles[btc_index - lookback].close - 1) * 100
                features = observable_features(candles, signal_index, lookback, btc_return, original)
                r0_event = add_opportunity_metrics(original, candles, initial_r=2 * float(original["atr14"]))
                r0_event["features"] = features
                rb1_event = add_opportunity_metrics(modified, candles, initial_r=float(modified["initial_r"]))
                rb1_event["features"] = features
                r0_rows.append(r0_event); rb1_rows.append(rb1_event)
        expected = baseline_by_id[parameter_id]["summary"]
        source_count = sum(len(json.loads(path.read_text(encoding="utf-8"))["event_sets"][checkpoint_index]) for path in R0_CHECKPOINTS.glob("*.json"))
        if source_count != int(expected["event_count"]):
            raise RuntimeError("RB-2 R-0 frozen source event reproduction mismatch")
        if [int(x["signal_time_ms"]) for x in r0_rows] != [int(x["signal_time_ms"]) for x in rb1_rows]:
            raise RuntimeError("RB-2 comparable signal identity differs between exits")
        for exit_id, rows in (("R0_FIXED_EXIT_2_ATR_STOP", r0_rows), ("RB1_ST_B_EX_B", rb1_rows)):
            profiles.append({"family_id": "OVERSOLD_REBOUND", "parameter_id": parameter_id, "parameters": {"return_lookback_candles": lookback, "minimum_drop_fraction": "0.10", "holding_candles": holding}, "exit_profile": exit_id, "signal_identity": {"frozen_r0_source_event_count": source_count, "comparable_event_count": len(rows), "source_matches_frozen_r0": True, "same_signals_across_exit_profiles": True, "exclusion_reason": "RB1_32_CANDLE_PATH_UNAVAILABLE_OR_NONPOSITIVE_INITIAL_R"}, "profile": profile_events(rows)})
    report = {
        "protocol": "ORBIT_RB2_OPPORTUNITY_PROFILE_REPORT_V1",
        "purpose": "DESCRIBE_SEMI_AUTOMATIC_SIGNAL_OPPORTUNITIES_ONLY",
        "contract_sha256": hashlib.sha256(spec_raw).hexdigest(),
        "dataset_fingerprint": context["manifest"]["dataset_fingerprint"],
        "training_end_ms": end_ms,
        "lockbox_opened": False,
        "lockbox_data_read": False,
        "selection_or_gate_effect": "NONE",
        "profiles": profiles,
        "honesty_boundary": ["MFE_IS_HINDSIGHT_REACHABLE_UPPER_BOUND_NOT_REALIZABLE_RETURN", "OBSERVABLE_FEATURE_DIFFERENCES_REQUIRE_INDEPENDENT_VALIDATION_BEFORE_ANY_FILTER_RULE"],
    }
    forbidden = ("verdict", "passed", "failed", "threshold")
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if any(f'"{word}"' in encoded.lower() for word in forbidden):
        raise RuntimeError("RB-2 descriptive report contains a forbidden decision field")
    _write_exclusive(Path(args.out), report)
    print(json.dumps({"output": str(Path(args.out).resolve()), "profiles": len(profiles)}, ensure_ascii=False))


if __name__ == "__main__": main()
