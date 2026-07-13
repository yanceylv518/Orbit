from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from statistics import fmean
from typing import Any, Sequence

from orbit.domain.strategy.exposure import TargetExposureDecision, strategy_body


RANGE = "RANGE"
TRENDING = "TRENDING"
TRANSITION = "TRANSITION"
UNKNOWN = "UNKNOWN"

DEFAULT_REGIME_CONFIG = {
    "enabled": True,
    "window": 30,
    "min_samples": 20,
    "confirm_ticks": 3,
    "range_efficiency_ratio": 0.35,
    "trend_efficiency_ratio": 0.65,
    "range_max_autocorrelation": 0.95,
    "trend_autocorrelation": 0.35,
    "min_volatility_pct": 0.01,
}


@dataclass(frozen=True)
class RegimeFeatures:
    sample_count: int
    efficiency_ratio: float
    return_autocorrelation: float
    volatility_pct: float

    def context(self) -> dict[str, float | int]:
        return {
            "sample_count": self.sample_count,
            "efficiency_ratio": round(self.efficiency_ratio, 6),
            "return_autocorrelation": round(self.return_autocorrelation, 6),
            "volatility_pct": round(self.volatility_pct, 6),
        }


@dataclass(frozen=True)
class RegimeGateResult:
    allowed: bool
    code: str
    reason: str
    context: dict[str, str]


def regime_config(strategy: dict[str, Any]) -> dict[str, Any]:
    return strategy_body(strategy).get("regime_gate", {})


def ensure_regime_gate_config(strategy: dict[str, Any]) -> dict[str, Any]:
    body = strategy_body(strategy)
    current = body.setdefault("regime_gate", {})
    for key, value in DEFAULT_REGIME_CONFIG.items():
        current.setdefault(key, value)
    return strategy


def market_features(prices: Sequence[float]) -> RegimeFeatures:
    clean = [float(price) for price in prices if float(price) > 0]
    if len(clean) < 2:
        return RegimeFeatures(len(clean), 0.0, 0.0, 0.0)

    changes = [clean[index] - clean[index - 1] for index in range(1, len(clean))]
    path = sum(abs(change) for change in changes)
    efficiency_ratio = abs(clean[-1] - clean[0]) / path if path else 0.0
    returns = [changes[index] / clean[index] for index in range(len(changes))]
    volatility_pct = _sample_std(returns) * 100
    autocorrelation = _lag_one_autocorrelation(returns)
    return RegimeFeatures(len(clean), efficiency_ratio, autocorrelation, volatility_pct)


def classify_regime(prices: Sequence[float], config: dict[str, Any]) -> tuple[str, RegimeFeatures]:
    features = market_features(prices)
    minimum = max(3, int(config.get("min_samples", 30)))
    if features.sample_count < minimum:
        return UNKNOWN, features
    if features.volatility_pct < float(config.get("min_volatility_pct", 0.01)):
        return UNKNOWN, features
    range_er = float(config.get("range_efficiency_ratio", 0.35))
    if (
        features.efficiency_ratio >= float(config.get("trend_efficiency_ratio", 0.65))
        or (
            features.efficiency_ratio > range_er
            and features.return_autocorrelation >= float(config.get("trend_autocorrelation", 0.35))
        )
    ):
        return TRENDING, features
    if (
        features.efficiency_ratio <= range_er
        and features.return_autocorrelation <= float(config.get("range_max_autocorrelation", 0.95))
    ):
        return RANGE, features
    return TRANSITION, features


class RegimeGate:
    def __init__(self, strategy: dict[str, Any]):
        self.config = regime_config(strategy)
        self.enabled = bool(self.config.get("enabled", False))

    def update(self, state: dict[str, Any], price: float) -> dict[str, Any]:
        if not self.enabled:
            state["regime"] = RANGE
            state["regime_stable"] = RANGE
            state["regime_gate_enabled"] = False
            return state

        window = max(3, int(self.config.get("window", 30)))
        history = [float(item) for item in state.get("regime_price_history", []) if float(item) > 0]
        history.append(float(price))
        history = history[-window:]
        raw, features = classify_regime(history, self.config)
        stable = str(state.get("regime_stable") or UNKNOWN)
        candidate = str(state.get("regime_candidate") or "")
        count = int(state.get("regime_candidate_count", 0))

        if raw == UNKNOWN:
            stable, candidate, count, visible = UNKNOWN, "", 0, UNKNOWN
        elif raw == stable:
            candidate, count, visible = "", 0, stable
        else:
            if raw == candidate:
                count += 1
            else:
                candidate, count = raw, 1
            required = max(1, int(self.config.get("confirm_ticks", 3)))
            if count >= required and raw in (RANGE, TRENDING):
                stable, candidate, count, visible = raw, "", 0, raw
            else:
                visible = TRANSITION

        state.update({
            "regime_gate_enabled": True,
            "regime": visible,
            "regime_stable": stable,
            "regime_raw": raw,
            "regime_candidate": candidate,
            "regime_candidate_count": count,
            "regime_price_history": history,
            "regime_features": features.context(),
        })
        return state

    def evaluate(self, decision: TargetExposureDecision, state: dict[str, Any]) -> RegimeGateResult:
        if not self.enabled:
            return RegimeGateResult(True, "REGIME_GATE_DISABLED", "regime gate is disabled", {})

        regime = str(state.get("regime") or UNKNOWN)
        event_type = str(decision.event_type or "")
        context = {
            "regime": regime,
            "regime_raw": str(state.get("regime_raw") or UNKNOWN),
            "regime_stable": str(state.get("regime_stable") or UNKNOWN),
        }
        if event_type.startswith("LOSS_SIDE_REDUCTION"):
            return RegimeGateResult(True, "REGIME_RISK_REDUCTION_ALLOWED", "risk reduction remains allowed", context)
        if event_type.startswith("POSITION_RECOVERY"):
            return RegimeGateResult(True, "REGIME_EXISTING_SKEW_MANAGEMENT", "existing skew may return toward neutral", context)
        if event_type.startswith("PROFIT_TRANSFER") or event_type == "POSITION_REBUILD":
            if regime == RANGE:
                return RegimeGateResult(True, "REGIME_RANGE_ALLOWED", "mean-reversion regime allows new grid risk", context)
            return RegimeGateResult(
                False,
                f"REGIME_{regime}_BLOCKED",
                "new grid risk requires a confirmed RANGE regime",
                context,
            )
        return RegimeGateResult(True, "REGIME_NO_NEW_RISK", "event does not add grid risk", context)


def _sample_std(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = fmean(values)
    return sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _lag_one_autocorrelation(values: Sequence[float]) -> float:
    if len(values) < 3:
        return 0.0
    left = values[:-1]
    right = values[1:]
    left_mean = fmean(left)
    right_mean = fmean(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = sqrt(
        sum((a - left_mean) ** 2 for a in left)
        * sum((b - right_mean) ** 2 for b in right)
    )
    return numerator / denominator if denominator else 0.0
