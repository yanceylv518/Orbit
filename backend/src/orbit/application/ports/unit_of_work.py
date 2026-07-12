from __future__ import annotations

from types import TracebackType
from typing import Protocol

from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.account_snapshot_repository import AccountSnapshotRepository
from orbit.application.ports.audit_repository import AuditRepository
from orbit.application.ports.execution_plan_repository import ExecutionPlanRepository
from orbit.application.ports.event_history_repository import EventHistoryRepository
from orbit.application.ports.report_repository import ReportRepository
from orbit.application.ports.metric_history_repository import MetricHistoryRepository
from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.application.ports.symbol_state_repository import SymbolStateRepository
from orbit.application.ports.strategy_runtime_repository import StrategyRuntimeRepository


class ApplicationUnitOfWork(Protocol):
    accounts: AccountRepository
    run_configs: RunConfigRepository
    snapshots: AccountSnapshotRepository
    symbol_states: SymbolStateRepository
    plans: ExecutionPlanRepository
    audits: AuditRepository
    events: EventHistoryRepository
    reports: ReportRepository
    strategy_runtime: StrategyRuntimeRepository
    metrics: MetricHistoryRepository

    def __enter__(self) -> "ApplicationUnitOfWork":
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...
