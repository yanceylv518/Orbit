from __future__ import annotations

import time
from typing import Any

from orbit.application.ports.audit_repository import AuditRepository
from orbit.domain.strategy.engine import now_iso


class AuditService:
    def __init__(self, repository: AuditRepository, strategy_id: str):
        self.repository = repository
        self.strategy_id = strategy_id

    def record(
        self,
        *,
        actor: str,
        action_type: str,
        reason: str,
        before_value: dict[str, Any] | None = None,
        after_value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        audit = {
            "id": f"audit_{time.time_ns()}",
            "timestamp": now_iso(),
            "admin_user_id": actor,
            "action_type": action_type,
            "target_strategy_id": self.strategy_id,
            "before_value": before_value or {},
            "after_value": after_value or {},
            "reason": reason,
        }
        self.repository.add(audit)
        return audit
