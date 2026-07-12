from __future__ import annotations

from copy import deepcopy
from typing import Any

from orbit.application.ports.strategy_runtime_repository import StrategyRuntimeRepository
from orbit.domain.strategy.engine import EventEngine


class StrategyEventConfigService:
    def __init__(self, runtime: StrategyRuntimeRepository):
        self.runtime = runtime

    def update(self, incoming: dict[str, Any], *, actor: str) -> dict[str, Any]:
        strategy = self.runtime.strategy()
        before = deepcopy(strategy["strategy"]["events"])
        strategy["strategy"]["events"] = self.merge_known(before, incoming)
        return {
            "ok": True,
            "engine": EventEngine(strategy),
            "event_config": deepcopy(strategy["strategy"]["events"]),
            "_audit": {
                "actor": actor,
                "action_type": "UPDATE_EVENT_CONFIG",
                "reason": "管理员更新三大策略事件参数。",
                "before_value": before,
                "after_value": deepcopy(strategy["strategy"]["events"]),
            },
        }

    def merge_known(self, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current)
        for key, current_value in current.items():
            if key not in incoming:
                continue
            incoming_value = incoming[key]
            if isinstance(current_value, dict) and isinstance(incoming_value, dict):
                merged[key] = self.merge_known(current_value, incoming_value)
            elif isinstance(current_value, bool):
                merged[key] = bool(incoming_value)
            elif isinstance(current_value, int) and not isinstance(current_value, bool):
                merged[key] = max(0, int(float(incoming_value)))
            elif isinstance(current_value, float):
                merged[key] = max(0.0, float(incoming_value))
            else:
                merged[key] = incoming_value
        return merged
