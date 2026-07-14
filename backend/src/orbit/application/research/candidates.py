from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


REQUIRED_FIELDS = {
    "id",
    "name",
    "signal_definition",
    "parameters",
    "costs",
    "matrix",
    "thresholds",
    "frozen_at",
    "status",
    "verdict",
    "lockbox_opened_at",
    "result_ids",
}


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def freeze_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    payload = {key: candidate[key] for key in candidate if key != "frozen_hash"}
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise ValueError(f"research candidate is missing fields: {', '.join(sorted(missing))}")
    if not str(payload["id"]).strip():
        raise ValueError("research candidate id is required")
    payload["frozen_hash"] = hashlib.sha256(canonical_json(payload)).hexdigest()
    return payload


INITIAL_CANDIDATES = (
    {
        "id": "M0",
        "name": "Unconditional anchor mean reversion",
        "signal_definition": "Bet on reversion after a fixed anchor deviation; evaluated against latency and costs.",
        "parameters": {"a_pct": [1.5, 2.0], "theta_pct": 4.0, "holding_ticks": [1, 4, 8, 24]},
        "costs": {"roundtrip_pct": 0.14},
        "matrix": {
            "markets": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
            "intervals": ["15m", "1h"],
            "horizons": 4,
        },
        "thresholds": {"required_positive_combinations": 1},
        "frozen_at": "2026-07-13T00:00:00Z",
        "status": "evaluated",
        "verdict": "NO_GO",
        "lockbox_opened_at": None,
        "result_ids": ["model_reassessment_15m_horizons", "model_reassessment_1h_horizons"],
    },
    {
        "id": "F1",
        "name": "Funding carry necessary-condition screen",
        "signal_definition": "Test whether positive funding can cover entry, exit, and rebalance costs.",
        "parameters": {"holding_settlements": [3, 9, 21]},
        "costs": {"entry_exit_pct": 0.38, "rebalance_pct_per_day": 0.02},
        "matrix": {"markets": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"]},
        "thresholds": {"required_markets": 3, "net_return_positive": True},
        "frozen_at": "2026-07-13T00:00:00Z",
        "status": "evaluated",
        "verdict": "NO_GO",
        "lockbox_opened_at": None,
        "result_ids": ["f1_funding_carry"],
    },
    {
        "id": "G1",
        "name": "Extreme funding reversal",
        "signal_definition": "Trade against historical funding extremes and test whether reversal covers costs.",
        "parameters": {
            "lookback_settlements": [90, 180, 360],
            "extreme_quantile": [0.9, 0.95, 0.99],
            "holding_ticks": [4, 12, 24, 48],
        },
        "costs": {"roundtrip_pct": 0.14},
        "matrix": {"configuration_count": 36, "required_markets": 3},
        "thresholds": {"positive_expected_value": True, "bootstrap_lower_bound_positive": True},
        "frozen_at": "2026-07-13T00:00:00Z",
        "status": "evaluated",
        "verdict": "NO_GO",
        "lockbox_opened_at": None,
        "result_ids": ["g1_extreme_funding_training"],
    },
    {
        "id": "G2",
        "name": "Funding relative-strength momentum",
        "signal_definition": "Long the highest-funding market and short the lowest-funding market.",
        "parameters": {"lookback_settlements": [3, 9, 21], "holding_settlements": [3, 9, 21]},
        "costs": {"roundtrip_pct": 0.14},
        "matrix": {
            "configuration_count": 9,
            "markets": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
        },
        "thresholds": {"min_market_appearances": 10, "positive_expected_value": True},
        "frozen_at": "2026-07-13T00:00:00Z",
        "status": "evaluated",
        "verdict": "NO_GO",
        "lockbox_opened_at": None,
        "result_ids": ["g2_funding_relative_strength_training"],
    },
)
