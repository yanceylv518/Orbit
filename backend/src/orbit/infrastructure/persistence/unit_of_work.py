from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from types import TracebackType

from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.audits import InMemoryAuditRepository
from orbit.infrastructure.persistence.execution_plans import InMemoryExecutionPlanRepository
from orbit.infrastructure.persistence.event_history import InMemoryEventHistoryRepository
from orbit.infrastructure.persistence.reports import InMemoryReportRepository
from orbit.infrastructure.persistence.metrics import InMemoryMetricHistoryRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository
from orbit.infrastructure.persistence.strategy_runtime import InMemoryStrategyRuntimeRepository


class InMemoryApplicationUnitOfWork:
    def __init__(
        self,
        accounts: ConfigAccountRepository,
        run_configs: InMemoryRunConfigRepository,
        snapshots: InMemoryAccountSnapshotRepository,
        symbol_states: InMemorySymbolStateRepository,
        plans: InMemoryExecutionPlanRepository,
        audits: InMemoryAuditRepository,
        events: InMemoryEventHistoryRepository,
        reports: InMemoryReportRepository,
        strategy_runtime: InMemoryStrategyRuntimeRepository,
        metrics: InMemoryMetricHistoryRepository,
        commit_callback: Callable[[], None],
    ):
        self.accounts = accounts
        self.run_configs = run_configs
        self.snapshots = snapshots
        self.symbol_states = symbol_states
        self.plans = plans
        self.audits = audits
        self.events = events
        self.reports = reports
        self.strategy_runtime = strategy_runtime
        self.metrics = metrics
        self.commit_callback = commit_callback
        self._account_snapshot: dict | None = None
        self._run_config_snapshot: list[dict] | None = None
        self._exchange_snapshot: dict | None = None
        self._symbol_state_snapshot: dict | None = None
        self._plan_snapshot: list[dict] | None = None
        self._audit_snapshot: list[dict] | None = None
        self._event_snapshot: dict | None = None
        self._report_snapshot: list[dict] | None = None
        self._strategy_runtime_snapshot: dict | None = None
        self._metric_snapshot: dict | None = None
        self._committed = False

    def __enter__(self) -> "InMemoryApplicationUnitOfWork":
        self._account_snapshot = self.accounts.snapshot()
        self._run_config_snapshot = self.run_configs.snapshot()
        self._exchange_snapshot = self.snapshots.snapshot()
        self._symbol_state_snapshot = deepcopy(self.symbol_states.all())
        self._plan_snapshot = self.plans.snapshot()
        self._audit_snapshot = self.audits.snapshot()
        self._event_snapshot = self.events.snapshot()
        self._report_snapshot = self.reports.snapshot()
        self._strategy_runtime_snapshot = self.strategy_runtime.snapshot()
        self._metric_snapshot = self.metrics.snapshot()
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        if exc_type is not None or not self._committed:
            self.rollback()
        self._account_snapshot = None
        self._run_config_snapshot = None
        self._exchange_snapshot = None
        self._symbol_state_snapshot = None
        self._plan_snapshot = None
        self._audit_snapshot = None
        self._event_snapshot = None
        self._report_snapshot = None
        self._strategy_runtime_snapshot = None
        self._metric_snapshot = None
        return False

    def commit(self) -> None:
        if any(snapshot is None for snapshot in (
            self._account_snapshot,
            self._run_config_snapshot,
            self._exchange_snapshot,
            self._symbol_state_snapshot,
            self._plan_snapshot,
            self._audit_snapshot,
            self._event_snapshot,
            self._report_snapshot,
            self._strategy_runtime_snapshot,
            self._metric_snapshot,
        )):
            raise RuntimeError("ApplicationUnitOfWork must be entered before commit().")
        self.commit_callback()
        self._committed = True

    def rollback(self) -> None:
        if self._account_snapshot is not None:
            self.accounts.restore(self._account_snapshot)
        if self._run_config_snapshot is not None:
            self.run_configs.restore(self._run_config_snapshot)
        if self._exchange_snapshot is not None:
            self.snapshots.restore(self._exchange_snapshot)
        if self._symbol_state_snapshot is not None:
            self.symbol_states.replace_all(self._symbol_state_snapshot)
        if self._plan_snapshot is not None:
            self.plans.restore(self._plan_snapshot)
        if self._audit_snapshot is not None:
            self.audits.restore(self._audit_snapshot)
        if self._event_snapshot is not None:
            self.events.restore(self._event_snapshot)
        if self._report_snapshot is not None:
            self.reports.restore(self._report_snapshot)
        if self._strategy_runtime_snapshot is not None:
            self.strategy_runtime.restore(self._strategy_runtime_snapshot)
        if self._metric_snapshot is not None:
            self.metrics.restore(self._metric_snapshot)
