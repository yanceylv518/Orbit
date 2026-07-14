from __future__ import annotations

from copy import deepcopy
from typing import Any


PROTOCOL_TEMPLATES: dict[str, dict[str, Any]] = {
    "M0": {
        "name": "Anchor mean-reversion horizon screen",
        "signal_definition": "Measure fixed-horizon reversion after a preregistered anchor excursion.",
        "parameters": {"a_pct": 1.5, "theta_pct": 4.0, "holding_ticks": [1, 4, 8, 24]},
        "costs": {"roundtrip_pct": 0.14},
        "thresholds": {"required_positive_combinations": 1},
        "dataset_rule": {"mode": "candles", "minimum": 1},
    },
    "F1": {
        "name": "Funding carry necessary-condition screen",
        "signal_definition": "Test whether funding carry can cover frozen entry, exit, and rebalance costs.",
        "parameters": {"holding_settlements": [3, 9, 21, 42, 90]},
        "costs": {"entry_exit_pct": 0.38, "rebalance_pct_per_day": 0.02},
        "thresholds": {"required_markets": 3, "net_return_positive": True},
        "dataset_rule": {"mode": "funding", "minimum": 3},
    },
    "G1": {
        "name": "Extreme funding reversal",
        "signal_definition": "Trade against historical funding extremes using preregistered grids.",
        "parameters": {
            "lookback_settlements": [90, 180, 360],
            "extreme_quantile": [0.9, 0.95, 0.975],
            "holding_ticks": [4, 16, 32, 96],
        },
        "costs": {"roundtrip_pct": 0.14},
        "thresholds": {
            "required_markets": 3,
            "positive_expected_value": True,
            "bootstrap_lower_bound_positive": True,
        },
        "dataset_rule": {"mode": "paired", "minimum_markets": 3, "candle_interval": "15m"},
    },
    "G2": {
        "name": "Funding relative-strength momentum",
        "signal_definition": "Long the highest-funding market and short the lowest-funding market.",
        "parameters": {"lookback_settlements": [3, 9, 21], "holding_settlements": [3, 9, 21]},
        "costs": {"roundtrip_pct": 0.14},
        "thresholds": {"min_market_appearances": 10, "positive_expected_value": True},
        "dataset_rule": {"mode": "paired", "exact_markets": 4, "candle_interval": "15m"},
    },
}


def protocol_templates() -> list[dict[str, Any]]:
    return [
        {"id": protocol_id, **deepcopy(template)}
        for protocol_id, template in PROTOCOL_TEMPLATES.items()
    ]


def build_candidate(payload: dict[str, Any], datasets: list[dict[str, Any]], frozen_at: str) -> dict[str, Any]:
    candidate_id = str(payload.get("id", "")).strip().upper()
    protocol_id = str(payload.get("protocol", "")).strip().upper()
    template = PROTOCOL_TEMPLATES.get(protocol_id)
    if not template:
        raise ValueError("unsupported research protocol")
    if not candidate_id or not candidate_id.replace("-", "").replace("_", "").isalnum():
        raise ValueError("candidate id must contain only letters, numbers, hyphens, or underscores")
    if len(candidate_id) > 32:
        raise ValueError("candidate id must not exceed 32 characters")
    name = str(payload.get("name", "")).strip() or str(template["name"])
    if len(name) > 120:
        raise ValueError("candidate name must not exceed 120 characters")
    selected = validate_datasets(template["dataset_rule"], datasets)
    markets = sorted({str(item["market"]) for item in selected if item.get("market")})
    intervals = sorted({str(item["interval"]) for item in selected if item.get("interval")})
    matrix: dict[str, Any] = {
        "dataset_ids": [item["id"] for item in selected],
        "dataset_sha256": {item["id"]: item["sha256"] for item in selected},
        "markets": markets,
    }
    if intervals:
        matrix["intervals"] = intervals
    return {
        "id": candidate_id,
        "name": name,
        "protocol": protocol_id,
        "signal_definition": template["signal_definition"],
        "parameters": deepcopy(template["parameters"]),
        "costs": deepcopy(template["costs"]),
        "matrix": matrix,
        "thresholds": deepcopy(template["thresholds"]),
        "frozen_at": frozen_at,
        "status": "frozen",
        "verdict": "PENDING",
        "lockbox_opened_at": None,
        "result_ids": [],
    }


def validate_datasets(rule: dict[str, Any], datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not datasets:
        raise ValueError("at least one cached dataset is required")
    if len({item["id"] for item in datasets}) != len(datasets):
        raise ValueError("dataset ids must be unique")
    mode = rule["mode"]
    if mode == "candles":
        if any(item.get("kind") not in {"ohlc", "series"} for item in datasets):
            raise ValueError("this protocol accepts candle or close-series datasets only")
        if len(datasets) < int(rule["minimum"]):
            raise ValueError("not enough candle datasets")
    elif mode == "funding":
        if any(item.get("kind") != "funding" for item in datasets):
            raise ValueError("this protocol accepts funding datasets only")
        if len(datasets) < int(rule["minimum"]):
            raise ValueError("not enough funding datasets")
    elif mode == "paired":
        by_market: dict[str, set[str]] = {}
        for item in datasets:
            market = item.get("market")
            if not market or item.get("kind") not in {"funding", "ohlc", "series"}:
                raise ValueError("paired protocols require market-labelled funding and candle datasets")
            kind = "candles" if item["kind"] in {"ohlc", "series"} else "funding"
            if kind == "candles" and rule.get("candle_interval") != item.get("interval"):
                raise ValueError(f"paired protocol requires {rule['candle_interval']} candle datasets")
            if kind in by_market.setdefault(str(market), set()):
                raise ValueError(f"market {market} has duplicate {kind} datasets")
            by_market[str(market)].add(kind)
        incomplete = [market for market, kinds in by_market.items() if kinds != {"funding", "candles"}]
        if incomplete:
            raise ValueError(f"markets require one funding and one candle dataset: {', '.join(incomplete)}")
        market_count = len(by_market)
        if rule.get("exact_markets") and market_count != int(rule["exact_markets"]):
            raise ValueError(f"this protocol requires exactly {rule['exact_markets']} paired markets")
        if rule.get("minimum_markets") and market_count < int(rule["minimum_markets"]):
            raise ValueError(f"this protocol requires at least {rule['minimum_markets']} paired markets")
    return sorted(datasets, key=lambda item: str(item["id"]))
