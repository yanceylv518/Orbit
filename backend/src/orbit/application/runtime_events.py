from __future__ import annotations

from typing import Any

from orbit.application.ports.event_history_repository import EventHistoryRepository


class RuntimeEventService:
    def __init__(self, repository: EventHistoryRepository, strategy_id: str):
        self.repository = repository
        self.strategy_id = strategy_id

    def record_engine_results(
        self,
        events: list[dict[str, Any]],
        risks: list[dict[str, Any]],
        *,
        account_id: str | None = None,
    ) -> None:
        for event in events:
            event["user_id"] = None
            event["exchange_account_id"] = account_id
            event["strategy_instance_id"] = self.strategy_id
            self.repository.add_strategy_event(event)
            for trade in event["trades"]:
                trade["strategy_event_id"] = event["id"]
                trade["user_id"] = None
                trade["exchange_account_id"] = account_id
                trade["strategy_instance_id"] = self.strategy_id
                self.repository.add_trade_event(trade)
        for risk in risks:
            risk["user_id"] = None
            risk["exchange_account_id"] = account_id
            risk["strategy_instance_id"] = self.strategy_id
            self.repository.add_risk_event(risk)
