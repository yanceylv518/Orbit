from __future__ import annotations

from copy import deepcopy
from typing import Any


class InMemoryExecutionPlanRepository:
    def __init__(self, plans: list[dict[str, Any]]):
        self.plans = plans

    def all(self) -> list[dict[str, Any]]:
        return self.plans

    def get(self, plan_id: str) -> dict[str, Any] | None:
        return next((plan for plan in self.plans if plan.get("id") == plan_id), None)

    def save(self, plan: dict[str, Any]) -> dict[str, Any]:
        existing = self.get(str(plan["id"]))
        if existing is None:
            self.plans.insert(0, plan)
            return plan
        if existing is not plan:
            existing.clear()
            existing.update(plan)
        return existing

    def replace_all(self, plans: list[dict[str, Any]]) -> None:
        if plans is self.plans:
            return
        self.plans.clear()
        self.plans.extend(plans[:300])

    def snapshot(self) -> list[dict[str, Any]]:
        return deepcopy(self.plans)

    def restore(self, plans: list[dict[str, Any]]) -> None:
        self.replace_all(deepcopy(plans))
