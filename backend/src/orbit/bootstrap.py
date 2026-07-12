from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable

from orbit.application.account_runtime import AccountRunConfigService
from orbit.application.account_sync import AccountSyncService
from orbit.application.accounts import AccountDirectoryService, AccountService
from orbit.application.audit import AuditService
from orbit.application.credentials import CredentialService
from orbit.application.execution_plans import ExecutionPlanRefreshService, ExecutionPlanService
from orbit.application.market_data import MarketFeedService
from orbit.application.metrics import MetricHistoryService
from orbit.application.permissions import PermissionPolicy
from orbit.application.portfolio_views import PortfolioViewService
from orbit.application.reporting import DailyReportService
from orbit.application.runtime_events import RuntimeEventService
from orbit.application.snapshot_queries import SnapshotQueryService
from orbit.application.strategy_config import StrategyEventConfigService
from orbit.application.strategy_control import StrategyControlService
from orbit.application.symbol_states import SymbolStateService
from orbit.infrastructure.credentials.account_connection import VaultAccountConnectionInspector
from orbit.infrastructure.credentials.local_vault import LocalCredentialVault
from orbit.infrastructure.exchange.binance_snapshots import BinanceSnapshotFetcher
from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.audits import InMemoryAuditRepository
from orbit.infrastructure.persistence.event_history import InMemoryEventHistoryRepository
from orbit.infrastructure.persistence.execution_plans import InMemoryExecutionPlanRepository
from orbit.infrastructure.persistence.metrics import InMemoryMetricHistoryRepository
from orbit.infrastructure.persistence.reports import InMemoryReportRepository
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.storage import make_state_store, mysql_status
from orbit.infrastructure.persistence.strategy_runtime import InMemoryStrategyRuntimeRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository
from orbit.infrastructure.persistence.unit_of_work import InMemoryApplicationUnitOfWork
from orbit.infrastructure.reporting.daily import DailyReportBuilder


@dataclass
class ApplicationContainer:
    account_repository: Any
    account_directory: Any
    account_service: Any
    credential_service: Any
    run_config_repository: Any
    account_snapshot_repository: Any
    run_config_service: Any
    symbol_state_repository: Any
    symbol_state_service: Any
    execution_plan_repository: Any
    audit_repository: Any
    event_history_repository: Any
    portfolio_views: Any
    report_repository: Any
    audit_service: Any
    runtime_event_service: Any
    daily_report_service: Any
    strategy_runtime_repository: Any
    strategy_control_service: Any
    strategy_config_service: Any
    metric_repository: Any
    metric_service: Any
    snapshot_queries: Any
    execution_plan_service: Any
    plan_refresh_service: Any
    account_sync_service: Any
    market_feed_service: Any
    app_uow: Any

    def install(self, target: Any) -> None:
        for field in fields(self):
            setattr(target, field.name, getattr(self, field.name))


def create_state_store(root: Path, config: dict[str, Any]) -> Any:
    return make_state_store(root, config["storage"], config)


class DefaultApplicationBootstrap:
    def create_state_store(self, root: Path, config: dict[str, Any]) -> Any:
        return create_state_store(root, config)

    def build_application_container(self, **kwargs: Any) -> ApplicationContainer:
        return build_application_container(**kwargs)


def create_app_state(config_path: str | None = None) -> Any:
    from orbit.application.app_state import AppState

    return AppState(DefaultApplicationBootstrap(), config_path=config_path)


def build_application_container(
    *,
    root: Path,
    config: dict[str, Any],
    strategy: dict[str, Any],
    engine: Any,
    runtime_state: dict[str, Any],
    account_run_configs: list[dict[str, Any]],
    account_snapshots: dict[str, dict[str, Any]],
    symbol_states: dict[str, dict[str, Any]],
    execution_plans: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    strategy_events: list[dict[str, Any]],
    trade_events: list[dict[str, Any]],
    risk_events: list[dict[str, Any]],
    reports: list[dict[str, Any]],
    metric_history: list[dict[str, Any]],
    symbol_metric_history: dict[str, list[dict[str, Any]]],
    persist: Callable[[], None],
    mock_data_enabled: bool,
) -> ApplicationContainer:
    permissions = PermissionPolicy()
    account_repository = ConfigAccountRepository(config)
    credential_vault = LocalCredentialVault()
    connection_inspector = VaultAccountConnectionInspector(credential_vault)
    account_directory = AccountDirectoryService(
        permissions,
        account_repository,
        connection_inspector,
    )
    account_service = AccountService(permissions, account_directory)
    credential_service = CredentialService(permissions, account_repository, credential_vault)

    run_config_repository = InMemoryRunConfigRepository(account_run_configs, config)
    account_snapshot_repository = InMemoryAccountSnapshotRepository(account_snapshots)
    run_config_service = AccountRunConfigService(
        permissions,
        account_repository,
        run_config_repository,
        strategy,
    )
    run_config_service.ensure_all()
    symbol_state_repository = InMemorySymbolStateRepository(symbol_states)
    symbol_state_service = SymbolStateService(
        strategy,
        engine,
        symbol_state_repository,
        account_repository,
        run_config_repository,
        account_snapshot_repository,
    )
    execution_plan_repository = InMemoryExecutionPlanRepository(execution_plans)
    audit_repository = InMemoryAuditRepository(audits)
    event_history_repository = InMemoryEventHistoryRepository(
        strategy_events,
        trade_events,
        risk_events,
    )
    portfolio_views = PortfolioViewService(
        config,
        strategy,
        account_directory,
        account_snapshot_repository,
        event_history_repository,
        mock_data_enabled=mock_data_enabled,
    )
    report_repository = InMemoryReportRepository(reports)
    audit_service = AuditService(audit_repository, strategy["id"])
    runtime_event_service = RuntimeEventService(event_history_repository, strategy["id"])
    daily_report_service = DailyReportService(DailyReportBuilder(root), report_repository)
    strategy_runtime_repository = InMemoryStrategyRuntimeRepository(strategy, runtime_state)
    strategy_control_service = StrategyControlService(strategy_runtime_repository, account_repository)
    strategy_config_service = StrategyEventConfigService(strategy_runtime_repository)
    metric_repository = InMemoryMetricHistoryRepository(metric_history, symbol_metric_history)
    metric_service = MetricHistoryService(metric_repository)
    plan_runtime = config.get("runtime", {})
    execution_plan_service = ExecutionPlanService(
        permissions,
        account_repository,
        run_config_repository,
        account_snapshot_repository,
        execution_plan_repository,
        symbol_state_repository,
        ttl_seconds=int(plan_runtime.get("plan_ttl_seconds", 900)),
        max_confirm_price_drift_pct=float(plan_runtime.get("plan_max_confirm_price_drift_pct", 0.5)),
    )
    execution_plan_service.snapshot_max_age_seconds = int(plan_runtime.get("snapshot_max_age_seconds", 600))
    plan_refresh_service = ExecutionPlanRefreshService(
        run_config_service,
        symbol_state_service,
        execution_plan_service,
        strategy,
        mock_data_enabled=mock_data_enabled,
    )
    account_sync_service = AccountSyncService(
        permissions,
        account_repository,
        account_snapshot_repository,
        BinanceSnapshotFetcher(credential_vault, connection_inspector),
        plan_refresh_service,
        strategy,
        mock_data_enabled=mock_data_enabled,
    )
    feed_config = config.get("runtime", {}).get("market_feed", {})
    market_feed_service = MarketFeedService(
        BinanceKlineFeed(),
        account_repository,
        run_config_repository,
        account_snapshot_repository,
        symbol_state_repository,
        symbol_state_service,
        runtime_state,
        interval=str(feed_config.get("interval", "1m")),
        limit=int(feed_config.get("limit", 3)),
    )
    market_feed_service.status["enabled"] = bool(feed_config.get("enabled", True)) and not mock_data_enabled
    snapshot_queries = SnapshotQueryService(
        config,
        strategy,
        permissions,
        account_directory,
        run_config_repository,
        account_snapshot_repository,
        execution_plan_repository,
        audit_repository,
        event_history_repository,
        report_repository,
        metric_repository,
        portfolio_views,
        lambda: {
            "driver": config["storage"].get("driver", "json"),
            "json_path": config["storage"].get("json_path", "var/data/runtime_state.json"),
            "mysql": mysql_status(),
        },
        mock_data_enabled=mock_data_enabled,
    )
    app_uow = InMemoryApplicationUnitOfWork(
        account_repository,
        run_config_repository,
        account_snapshot_repository,
        symbol_state_repository,
        execution_plan_repository,
        audit_repository,
        event_history_repository,
        report_repository,
        strategy_runtime_repository,
        metric_repository,
        persist,
    )
    return ApplicationContainer(
        account_repository=account_repository,
        account_directory=account_directory,
        account_service=account_service,
        credential_service=credential_service,
        run_config_repository=run_config_repository,
        account_snapshot_repository=account_snapshot_repository,
        run_config_service=run_config_service,
        symbol_state_repository=symbol_state_repository,
        symbol_state_service=symbol_state_service,
        execution_plan_repository=execution_plan_repository,
        audit_repository=audit_repository,
        event_history_repository=event_history_repository,
        portfolio_views=portfolio_views,
        report_repository=report_repository,
        audit_service=audit_service,
        runtime_event_service=runtime_event_service,
        daily_report_service=daily_report_service,
        strategy_runtime_repository=strategy_runtime_repository,
        strategy_control_service=strategy_control_service,
        strategy_config_service=strategy_config_service,
        metric_repository=metric_repository,
        metric_service=metric_service,
        snapshot_queries=snapshot_queries,
        execution_plan_service=execution_plan_service,
        plan_refresh_service=plan_refresh_service,
        account_sync_service=account_sync_service,
        market_feed_service=market_feed_service,
        app_uow=app_uow,
    )
