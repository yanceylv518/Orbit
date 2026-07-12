from __future__ import annotations

from typing import Any, Protocol


class ExecutionPlanRepository(Protocol):
    def all(self) -> list[dict[str, Any]]:
        ...

    def get(self, plan_id: str) -> dict[str, Any] | None:
        ...

    def save(self, plan: dict[str, Any]) -> dict[str, Any]:
        ...

    def replace_all(self, plans: list[dict[str, Any]]) -> None:
        ...
