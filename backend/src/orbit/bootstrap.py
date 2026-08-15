from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields
import json
from pathlib import Path
from typing import Any, Callable

from orbit.application.account_runtime import AccountRunConfigService
from orbit.application.account_sync import AccountSyncService
from orbit.application.accounts import AccountDirectoryService, AccountService
from orbit.application.audit import AuditService
from orbit.application.credentials import CredentialService
from orbit.application.data_summary import DataSummaryService
from orbit.application.execution_plans import ExecutionPlanRefreshService, ExecutionPlanService
from orbit.application.market_data import MarketFeedService
from orbit.application.market_directory import MarketDirectoryService
from orbit.application.message_center import MessageCenter
from orbit.application.data_update_scheduler import DataUpdateScheduler
from orbit.application.metrics import MetricHistoryService
from orbit.application.live_reconciliation import LiveReconciliationService
from orbit.application.live_execution import LiveExecutionService
from orbit.application.order_execution import OrderExecutionService
from orbit.application.paper_execution import PaperExecutionService
from orbit.application.permissions import PermissionPolicy
from orbit.application.portfolio_views import PortfolioViewService
from orbit.application.reporting import DailyReportService
from orbit.application.research.catalog import ResearchCatalogService
from orbit.application.research.runs import CachedToolEvaluator, ResearchWorkflowService
from orbit.application.runtime_events import RuntimeEventService
from orbit.application.snapshot_queries import SnapshotQueryService
from orbit.application.signals.desk import SignalDeskService
from orbit.application.strategy_config import StrategyEventConfigService
from orbit.application.strategy_catalog import StrategyCatalogService
from orbit.application.strategy_control_plane import (
    StrategyControlPlaneService,
    legacy_tb4_control_plane_projection,
)
from orbit.application.strategy_control import StrategyControlService
from orbit.application.symbol_states import SymbolStateService
from orbit.application.symbol_recovery import SymbolRecoveryService
from orbit.application.trend_forward import TrendForwardService
from orbit.application.trend_forward_market import TrendForwardMarketDriver
from orbit.application.trend_execution_checklist import (
    TrendExecutionChecklistProjector,
    load_tb4_exchange_rules,
)
from orbit.infrastructure.credentials.account_connection import VaultAccountConnectionInspector
from orbit.infrastructure.credentials.factory import create_credential_vault
from orbit.infrastructure.exchange.binance import BinanceFuturesClient
from orbit.infrastructure.exchange.binance_snapshots import BinanceSnapshotFetcher
from orbit.infrastructure.exchange.kline_feed import BinanceKlineFeed
from orbit.infrastructure.notifications.pushover import PushoverNotifier
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.accounts import ConfigAccountRepository
from orbit.infrastructure.persistence.audits import InMemoryAuditRepository
from orbit.infrastructure.persistence.event_history import InMemoryEventHistoryRepository
from orbit.infrastructure.persistence.execution_plans import InMemoryExecutionPlanRepository
from orbit.infrastructure.persistence.metrics import InMemoryMetricHistoryRepository
from orbit.infrastructure.persistence.live_equity_ledger import AppendOnlyLiveEquityLedger
from orbit.infrastructure.persistence.live_execution_ledger import AppendOnlyLiveExecutionLedger
from orbit.infrastructure.persistence.reports import InMemoryReportRepository
from orbit.infrastructure.persistence.research_registry import AppendOnlyResearchRegistry
from orbit.infrastructure.persistence.research_runs import AppendOnlyResearchRunLedger
from orbit.infrastructure.persistence.run_configs import InMemoryRunConfigRepository
from orbit.infrastructure.persistence.storage import make_state_store, mysql_status
from orbit.infrastructure.persistence.strategy_runtime import InMemoryStrategyRuntimeRepository
from orbit.infrastructure.persistence.strategy_control_plane import InMemoryStrategyControlPlaneRepository
from orbit.infrastructure.persistence.symbol_states import InMemorySymbolStateRepository
from orbit.infrastructure.persistence.trend_forward_ledger import TrendForwardLedger
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
    symbol_recovery_service: Any
    strategy_config_service: Any
    metric_repository: Any
    metric_service: Any
    snapshot_queries: Any
    execution_plan_service: Any
    plan_refresh_service: Any
    account_sync_service: Any
    market_feed_service: Any
    paper_execution_service: Any
    order_execution_service: Any
    trend_forward_snapshot: Any
    trend_forward_poll: Any
    live_reconciliation_service: Any
    live_execution_service: Any
    credential_vault: Any
    trend_checklist_projector: Any
    trend_forward_cache_invalidate: Any
    strategy_catalog_service: Any
    strategy_control_plane_repository: Any
    strategy_control_plane_service: Any
    data_summary: Any
    market_directory: Any
    research_catalog: Any
    research_workflow: Any
    signal_desk: Any
    message_center: Any
    data_update_scheduler: Any
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
    live_pilot_control: dict[str, Any],
    strategy_control_plane_records: dict[str, Any] | None = None,
    strategy_control_plane_repository: Any | None = None,
) -> ApplicationContainer:
    permissions = PermissionPolicy()
    account_repository = ConfigAccountRepository(config)
    credential_vault = create_credential_vault(config)
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
    symbol_recovery_service = SymbolRecoveryService(
        permissions,
        account_repository,
        symbol_state_repository,
        engine,
    )
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
        BinanceKlineFeed(base_url=str(feed_config.get("base_url", "https://fapi.binance.com"))),
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
    paper_execution_service = PaperExecutionService(
        engine,
        run_config_repository,
        symbol_state_repository,
        runtime_event_service,
    )
    order_execution_service = OrderExecutionService(
        permissions,
        account_repository,
        run_config_repository,
        execution_plan_repository,
        execution_plan_service,
        BinanceFuturesClient.from_account,
        live_trading_enabled=bool(plan_runtime.get("live_trading_enabled", False)),
        live_confirm_phrase=str(plan_runtime.get("live_confirm_phrase", "I UNDERSTAND LIVE TRADING")),
    )
    research_config = plan_runtime.get("research", {})
    calibration_dir = Path(str(research_config.get("calibration_dir", "var/calibration")))
    if not calibration_dir.is_absolute():
        calibration_dir = root / calibration_dir
    registry_path = Path(str(research_config.get("registry_path", "var/research/registry.jsonl")))
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    run_ledger_path = Path(str(research_config.get("run_ledger_path", "var/research/runs.jsonl")))
    if not run_ledger_path.is_absolute():
        run_ledger_path = root / run_ledger_path
    run_ledger = AppendOnlyResearchRunLedger(run_ledger_path)
    data_summary = DataSummaryService(calibration_dir / "shortline-data-v1")
    market_directory = MarketDirectoryService(
        base_url=str(feed_config.get("base_url", "https://fapi.binance.com")),
        minimum_volume_usdt=float(research_config.get("current_market_minimum_volume_usdt", 30_000_000)),
    )
    research_catalog = ResearchCatalogService(
        calibration_dir,
        AppendOnlyResearchRegistry(registry_path),
        run_ledger,
    )
    research_workflow = ResearchWorkflowService(
        research_catalog,
        run_ledger,
        CachedToolEvaluator(
            root,
            calibration_dir,
            shortline_enabled=bool(research_config.get("shortline_jobs_enabled", True)),
            shortline_min_free_gb=float(research_config.get("shortline_min_free_gb", 15)),
            shortline_verify_sample_symbols=int(
                research_config.get("shortline_verify_sample_symbols", 3)
            ),
        ),
    )
    signal_config = plan_runtime.get("signals", {})
    signal_ledger_directory = Path(
        str(signal_config.get("ledger_directory", "var/signals/sig1"))
    )
    if not signal_ledger_directory.is_absolute():
        signal_ledger_directory = root / signal_ledger_directory
    signal_interaction_directory = Path(
        str(signal_config.get("interaction_ledger_directory", "var/signals/sig2"))
    )
    if not signal_interaction_directory.is_absolute():
        signal_interaction_directory = root / signal_interaction_directory
    signal_spec_path = root / "config" / "signals" / "sig1.v1.json"
    signal_spec = json.loads(signal_spec_path.read_text(encoding="utf-8")) if signal_spec_path.exists() else {}
    signal_desk = SignalDeskService(
        signal_ledger_directory,
        signal_interaction_directory,
        vault=credential_vault,
        notifier_factory=lambda **references: PushoverNotifier(credential_vault, **references),
        account_repository=account_repository,
        binding_reader=lambda: strategy_control_plane_service.bindings(),
        gateway_factory=lambda account: BinanceFuturesClient.from_account(account, credential_vault),
        spec=signal_spec,
    )
    message_directory = root / str(plan_runtime.get("messages", {}).get("directory", "var/messages"))
    push = signal_config.get("pushover", {})
    message_notifier = None
    if push.get("api_token_reference") and push.get("user_key_reference"):
        message_notifier = PushoverNotifier(
            credential_vault,
            api_token_reference=push["api_token_reference"],
            user_key_reference=push["user_key_reference"],
        )
    message_center = MessageCenter(
        message_directory,
        notifier=message_notifier,
        push_important=bool(plan_runtime.get("messages", {}).get("push_important", False)),
    )

    def start_daily_data_job() -> Any:
        return research_workflow.create_shortline_dataset_build(
            {"confirm_full_download": True, "workers": 4}
        )

    data_update_scheduler = DataUpdateScheduler(
        start_daily_data_job, message_center, state_path=message_directory / "data_update_state.json"
    )
    trend_config = plan_runtime.get("trend_forward", {})
    live_control = live_pilot_control
    trend_data_dir = Path(str(trend_config.get("data_dir", "var/forward/tb4")))
    if not trend_data_dir.is_absolute():
        trend_data_dir = root / trend_data_dir
    trend_rules_path_value = str(trend_config.get("exchange_rules_path") or "").strip()
    trend_rules_path = Path(trend_rules_path_value) if trend_rules_path_value else None
    if trend_rules_path is not None and not trend_rules_path.is_absolute():
        trend_rules_path = root / trend_rules_path
    if trend_rules_path is None:
        console_rules_path = root / "var" / "forward" / "live-small" / "tb4_exchange_rules.json"
        if console_rules_path.exists():
            trend_rules_path = console_rules_path
    trend_checklist_projector = TrendExecutionChecklistProjector(
        live_capital_usdt=live_control.get(
            "live_capital_usdt", trend_config.get("live_capital_usdt", 500),
        ),
        exposure_multiplier=live_control.get("exposure_multiplier", 3),
        exchange_rules=load_tb4_exchange_rules(trend_rules_path),
    )
    trend_snapshot_cache: dict[str, Any] = {"signature": None, "snapshot": None}

    def trend_forward_snapshot() -> dict[str, Any]:
        ledger = TrendForwardLedger(trend_data_dir)
        signature = tuple(
            (
                path.stat().st_mtime_ns,
                path.stat().st_size,
            ) if path.exists() else None
            for path in (ledger.manifest_path, ledger.events_path)
        )
        if trend_snapshot_cache["signature"] != signature:
            trend_snapshot_cache["snapshot"] = TrendForwardService(
                ledger, trend_checklist_projector,
            ).snapshot()
            trend_snapshot_cache["signature"] = signature
        return deepcopy(trend_snapshot_cache["snapshot"])

    def trend_forward_poll() -> dict[str, Any]:
        service = TrendForwardService(
            TrendForwardLedger(trend_data_dir),
            trend_checklist_projector,
        )
        if not service.ledger.manifest():
            return {"ticks": 0, "status": "NOT_STARTED", "snapshot": service.snapshot()}
        driver = TrendForwardMarketDriver(
            BinanceKlineFeed(
                base_url=str(
                    trend_config.get("base_url", "https://fapi.binance.com")
                )
            ),
            service,
        )
        result = driver.poll_once()
        trend_snapshot_cache["signature"] = None
        return result

    def trend_forward_cache_invalidate() -> None:
        trend_snapshot_cache["signature"] = None

    live_equity_path = Path(str(
        trend_config.get(
            "equity_ledger_path",
            "var/forward/live-small/equity.jsonl",
        )
    ))
    if not live_equity_path.is_absolute():
        live_equity_path = root / live_equity_path
    live_equity_ledger = AppendOnlyLiveEquityLedger(live_equity_path)
    live_reconciliation_service = LiveReconciliationService(
        live_account_id=str(live_control.get("live_account_id") or ""),
        account_snapshots=account_snapshot_repository,
        trend_forward_snapshot=trend_forward_snapshot,
        equity_ledger=live_equity_ledger,
        quantity_tolerance_pct=float(
            trend_config.get("quantity_tolerance_pct", 1.0)
        ),
    )
    execution_ledger_path = Path(str(
        trend_config.get(
            "execution_ledger_path",
            "var/forward/live-small/executions.jsonl",
        )
    ))
    if not execution_ledger_path.is_absolute():
        execution_ledger_path = root / execution_ledger_path
    live_execution_service = LiveExecutionService(
        enabled=bool(live_control.get("auto_execution_enabled", False)),
        execution_epoch=str(live_control.get("execution_epoch") or ""),
        live_account_id=str(live_control.get("live_account_id") or ""),
        accounts=account_repository,
        account_snapshots=account_snapshot_repository,
        trend_forward_snapshot=trend_forward_snapshot,
        gateway_factory=lambda account: BinanceFuturesClient.from_account(
            account, credential_vault,
        ),
        execution_ledger=AppendOnlyLiveExecutionLedger(execution_ledger_path),
        equity_ledger=live_equity_ledger,
        reconciliation_snapshot=live_reconciliation_service.snapshot,
        max_snapshot_age_seconds=int(
            live_control.get(
                "max_snapshot_age_seconds",
                trend_config.get("max_snapshot_age_seconds", 120),
            )
        ),
        max_order_notional_usdt=float(
            live_control.get(
                "max_order_notional_usdt",
                trend_config.get("max_order_notional_usdt", 150),
            )
        ),
        round_gross_multiplier=float(
            live_control.get(
                "round_gross_multiplier",
                trend_config.get("round_gross_multiplier", 1.1),
            )
        ),
    )
    strategy_catalog_service = StrategyCatalogService(
        trend_forward_snapshot,
        live_execution_service.snapshot,
        live_capital_usdt=float(live_control.get("live_capital_usdt", 500)),
        live_configured=bool(str(live_control.get("live_account_id") or "").strip()),
    )
    if strategy_control_plane_repository is None:
        control_plane_records = (
            strategy_control_plane_records
            or legacy_tb4_control_plane_projection(
                live_control,
                live_execution_service.snapshot,
            )
        )
        strategy_control_plane_repository = InMemoryStrategyControlPlaneRepository(
            control_plane_records,
        )
    strategy_control_plane_service = StrategyControlPlaneService(
        strategy_control_plane_repository,
    )

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
        trend_forward_snapshot,
        mock_data_enabled=mock_data_enabled,
        live_reconciliation_snapshot=live_reconciliation_service.snapshot,
        live_execution_snapshot=live_execution_service.snapshot,
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
        symbol_recovery_service=symbol_recovery_service,
        strategy_config_service=strategy_config_service,
        metric_repository=metric_repository,
        metric_service=metric_service,
        snapshot_queries=snapshot_queries,
        execution_plan_service=execution_plan_service,
        plan_refresh_service=plan_refresh_service,
        account_sync_service=account_sync_service,
        market_feed_service=market_feed_service,
        paper_execution_service=paper_execution_service,
        order_execution_service=order_execution_service,
        trend_forward_snapshot=trend_forward_snapshot,
        trend_forward_poll=trend_forward_poll,
        live_reconciliation_service=live_reconciliation_service,
        live_execution_service=live_execution_service,
        credential_vault=credential_vault,
        trend_checklist_projector=trend_checklist_projector,
        trend_forward_cache_invalidate=trend_forward_cache_invalidate,
        strategy_catalog_service=strategy_catalog_service,
        strategy_control_plane_repository=strategy_control_plane_repository,
        strategy_control_plane_service=strategy_control_plane_service,
        data_summary=data_summary,
        market_directory=market_directory,
        research_catalog=research_catalog,
        research_workflow=research_workflow,
        signal_desk=signal_desk,
        message_center=message_center,
        data_update_scheduler=data_update_scheduler,
        app_uow=app_uow,
    )
