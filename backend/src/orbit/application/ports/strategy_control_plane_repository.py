from __future__ import annotations

from typing import Protocol

from orbit.domain.strategy_control_plane import StrategyControlPlaneSnapshot


class StrategyControlPlaneRepository(Protocol):
    def snapshot(self) -> StrategyControlPlaneSnapshot:
        ...
