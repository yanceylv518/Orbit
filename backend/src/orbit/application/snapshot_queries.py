from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from orbit.application.auth import sanitize_user
from orbit.domain.strategy.engine import now_iso


class SnapshotQueryService:
    """Builds the console snapshot and applies account-level visibility rules."""

    def __init__(
        self,
        config: dict[str, Any],
        strategy: dict[str, Any],
        permissions: Any,
        account_directory: Any,
        run_configs: Any,
        account_snapshots: Any,
        execution_plans: Any,
        audits: Any,
        event_history: Any,
        reports: Any,
        metrics: Any,
        portfolio_views: Any,
        storage_status: Callable[[], dict[str, Any]],
        *,
        mock_data_enabled: bool,
    ) -> None:
        self.config = config
        self.strategy = strategy
        self.permissions = permissions
        self.account_directory = account_directory
        self.run_configs = run_configs
        self.account_snapshots = account_snapshots
        self.execution_plans = execution_plans
        self.audits = audits
        self.event_history = event_history
        self.reports = reports
        self.metrics = metrics
        self.portfolio_views = portfolio_views
        self.storage_status = storage_status
        self.mock_data_enabled = mock_data_enabled

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "server_time": now_iso(),
            "auth": {
                "authenticated": False,
                "login_required": self.login_required(),
            },
        }

    def snapshot(
        self,
        *,
        running: bool,
        tick_index: int,
        symbol_states: dict[str, dict[str, Any]],
        price_history: dict[str, list[dict[str, Any]]],
        current_user: dict[str, Any] | None = None,
        include_internal_history: bool = False,
        market_feed: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        symbols = self.portfolio_views.runtime_symbols(symbol_states)
        totals = self.portfolio_views.totals(symbols)
        trade_events = self.event_history.trade_events()[:120] if include_internal_history else []
        metric_history = self.metrics.all() if include_internal_history else []
        symbol_metric_history = self.metrics.by_symbol() if include_internal_history else {}
        payload = {
            "server_time": now_iso(),
            "running": running,
            "tick_index": tick_index,
            "users": self.config["users"],
            "exchange_accounts": self.account_directory.sanitize_accounts(self.config["exchange_accounts"]),
            "account_run_configs": deepcopy(self.run_configs.all()),
            "strategy": self.portfolio_views.strategy_summary(symbols, totals, running=running),
            "admin_overview": self.portfolio_views.admin_overview(symbols),
            "symbols": symbols,
            "strategy_events": deepcopy(self.event_history.strategy_events()[:80]),
            "trade_events": deepcopy(trade_events),
            "risk_events": deepcopy(self.event_history.risk_events()[:60]),
            "admin_audit_logs": deepcopy(self.audits.all()[:60]),
            "daily_reports": deepcopy(self.reports.all()[:30]),
            "binance_account_snapshots": deepcopy(self.account_snapshots.all()),
            "execution_plans": deepcopy(self.execution_plans.all()[:120]),
            "price_history": deepcopy(price_history),
            "metric_history": deepcopy(metric_history),
            "symbol_metric_history": deepcopy(symbol_metric_history),
            "event_config": self.strategy["strategy"]["events"],
            "storage": self.storage_status(),
            "market_feed": deepcopy(market_feed) if market_feed else None,
            "plan_symbol_states": self.plan_symbol_state_rows(symbol_states),
        }
        if not current_user:
            return payload
        filtered = self.apply_permissions(payload, current_user, running=running)
        filtered["auth"] = {
            "authenticated": True,
            "login_required": self.login_required(),
            "current_user": sanitize_user(current_user),
            "permissions": self.permissions.capabilities(current_user),
        }
        return filtered

    def plan_symbol_state_rows(self, symbol_states: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """账户级生命周期状态摘要：前端相位/Δ 可视化的直接数据源（脱离计划存在）。"""
        if self.mock_data_enabled:
            return []
        rows = []
        for key, state in symbol_states.items():
            account_id = state.get("account_id") or state.get("exchange_account_id")
            if not account_id:
                continue
            long_qty = float(state.get("long_qty") or 0)
            short_qty = float(state.get("short_qty") or 0)
            rows.append({
                "account_id": account_id,
                "symbol": state.get("symbol") or key.split("::")[-1],
                "state": state.get("state", "BALANCED"),
                "base_price": float(state.get("base_price") or 0),
                "last_price": float(state.get("last_price") or 0),
                "base_qty": float(state.get("base_qty") or 0),
                "long_qty": long_qty,
                "short_qty": short_qty,
                "delta_qty": long_qty - short_qty,
                "trend_extreme_price": float(state.get("trend_extreme_price") or 0),
                "trend_exit_candidate_count": int(state.get("trend_exit_candidate_count") or 0),
                "profit_transfer_count_in_trend": int(state.get("profit_transfer_count_in_trend") or 0),
                "loss_side_reduce_count_in_trend": int(state.get("loss_side_reduce_count_in_trend") or 0),
                "recovery_count_in_trend": int(state.get("recovery_count_in_trend") or 0),
                "tick_count": int(state.get("tick_count") or 0),
                "last_kline_at": state.get("last_kline_at"),
                "last_kline_close_time": state.get("last_kline_close_time"),
                "regime": state.get("regime", "UNKNOWN"),
                "regime_raw": state.get("regime_raw", "UNKNOWN"),
                "regime_stable": state.get("regime_stable", "UNKNOWN"),
                "regime_candidate_count": int(state.get("regime_candidate_count") or 0),
                "regime_features": deepcopy(state.get("regime_features") or {}),
            })
        return sorted(rows, key=lambda item: (item["account_id"], item["symbol"]))

    def apply_permissions(
        self,
        payload: dict[str, Any],
        current_user: dict[str, Any],
        *,
        running: bool,
    ) -> dict[str, Any]:
        if self.permissions.is_admin(current_user):
            return payload

        user_id = current_user["id"]
        visible_account_ids = self.account_directory.visible_account_ids(current_user)
        visible_accounts = [
            account for account in payload["exchange_accounts"]
            if account.get("id") in visible_account_ids
        ]
        account_ids = {account["id"] for account in visible_accounts}
        filtered = deepcopy(payload)
        filtered["users"] = [user for user in payload["users"] if user.get("id") == user_id]
        filtered["exchange_accounts"] = visible_accounts
        filtered["account_run_configs"] = [
            item for item in payload.get("account_run_configs", [])
            if item.get("account_id") in account_ids
        ]
        filtered["binance_account_snapshots"] = {
            account_id: snapshot
            for account_id, snapshot in payload.get("binance_account_snapshots", {}).items()
            if account_id in account_ids
        }
        filtered["admin_overview"] = {
            "users": [
                user for user in payload["admin_overview"]["users"]
                if user.get("user_id") == user_id
            ],
            "accounts": [
                account for account in payload["admin_overview"]["accounts"]
                if account.get("user_id") == user_id
            ],
            "permissions": {
                "can_view_all_accounts": False,
                "can_emergency_stop": False,
                "can_resume_dry_run": False,
                "can_view_secret": False,
            },
        }
        filtered["strategy_events"] = [
            event for event in payload["strategy_events"]
            if event.get("user_id") == user_id
        ]
        filtered["trade_events"] = [
            event for event in payload["trade_events"]
            if event.get("user_id") == user_id
        ]
        filtered["risk_events"] = [
            event for event in payload["risk_events"]
            if event.get("user_id") in (user_id, None)
        ]
        filtered["plan_symbol_states"] = [
            row for row in payload.get("plan_symbol_states", [])
            if row.get("account_id") in account_ids
        ]
        filtered["execution_plans"] = [
            plan for plan in payload.get("execution_plans", [])
            if plan.get("account_id") in account_ids
        ]
        if not self.mock_data_enabled:
            filtered["symbols"] = self.portfolio_views.real_symbol_views(account_ids)
            filtered["strategy"] = self.portfolio_views.strategy_summary(
                filtered["symbols"],
                self.portfolio_views.totals(filtered["symbols"]),
                running=running,
                account_ids=account_ids,
            )
        else:
            filtered["symbols"] = []
            filtered["price_history"] = {}
            filtered["symbol_metric_history"] = {}
            filtered["strategy"] = {
                "id": None,
                "name": "Unassigned strategy",
                "version": "-",
                "mode": "-",
                "status": "unassigned",
                "symbol_count": 0,
                "symbols": [],
                "today_pnl": 0,
                "today_pnl_pct": 0,
                "total_equity": 0,
                "risk_status": "normal",
            }
        return filtered

    def login_required(self) -> bool:
        return bool(self.config.get("auth", {}).get("login_required", False))
