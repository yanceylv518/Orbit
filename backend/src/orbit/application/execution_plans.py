from __future__ import annotations

import time
from copy import deepcopy
from typing import Any

from orbit.application.permissions import PermissionPolicy
from orbit.application.account_runtime import AccountRunConfigService
from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.account_snapshot_repository import AccountSnapshotRepository
from orbit.application.ports.execution_plan_repository import ExecutionPlanRepository
from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.application.symbol_states import SymbolStateService
from orbit.domain.planning.plans import DEFAULT_PLAN_TTL_SECONDS, generate_account_execution_plans
from orbit.domain.strategy.engine import now_iso
from orbit.domain.strategy.state_keys import lookup_plan_state, states_for_account


class ExecutionPlanService:
    """Application use cases for first-stage read-only execution plans."""

    def __init__(
        self,
        permissions: PermissionPolicy,
        accounts: AccountRepository,
        run_configs: RunConfigRepository,
        snapshots: AccountSnapshotRepository,
        plans: ExecutionPlanRepository,
        symbol_states: Any = None,
        *,
        ttl_seconds: int = DEFAULT_PLAN_TTL_SECONDS,
        max_confirm_price_drift_pct: float = 0.5,
    ):
        self.permissions = permissions
        self.accounts = accounts
        self.run_configs = run_configs
        self.snapshots = snapshots
        self.plans = plans
        self.symbol_states = symbol_states  # SymbolStateRepository | None，确认时的漂移校验
        self.ttl_seconds = int(ttl_seconds)
        self.max_confirm_price_drift_pct = float(max_confirm_price_drift_pct)
        self.snapshot_max_age_seconds = 600

    def build_for_accounts(
        self,
        *,
        account_ids: set[str],
        strategy: dict[str, Any],
        symbol_states: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        run_config_by_account = {
            item.get("account_id"): item
            for item in self.run_configs.all()
            if item.get("account_id")
        }
        selected_accounts = [
            account
            for account in self.accounts.accounts()
            if account.get("id") in account_ids
        ]

        portfolio_stopped = self.portfolio_stopped(strategy)
        new_plans: list[dict[str, Any]] = []
        for account in selected_accounts:
            account_id = str(account.get("id", ""))
            run_config = run_config_by_account.get(account_id)
            if not run_config:
                continue
            snapshot = self.snapshots.get(account_id)
            # 只传本账户的 symbol -> state 视图，防止跨账户读到别人的锚点/相位
            account_states = states_for_account(symbol_states or {}, account_id)
            new_plans.extend(generate_account_execution_plans(
                account,
                run_config,
                strategy,
                snapshot,
                symbol_states=account_states,
                ttl_seconds=self.ttl_seconds,
                portfolio_stopped=portfolio_stopped,
                snapshot_max_age_seconds=self.snapshot_max_age_seconds,
            ))

        retained_plans = [
            plan
            for plan in self.plans.all()
            if plan.get("account_id") not in account_ids
        ]
        plans = (new_plans + retained_plans)[:300]
        self.plans.replace_all(plans)
        return {
            "new_plans": new_plans,
            "plans": plans,
        }

    def confirm(
        self,
        *,
        plan_id: str,
        actor: str,
        actor_user: dict[str, Any] | None,
        note: str | None,
    ) -> dict[str, Any]:
        normalized_plan_id = str(plan_id or "").strip()
        normalized_note = str(note or "").strip()
        plan = self.plans.get(normalized_plan_id)
        if not plan:
            return {"ok": False, "error": f"执行计划不存在：{normalized_plan_id}"}

        account = self.accounts.account_by_id(str(plan.get("account_id", "")))
        if not self.permissions.can_access_account(actor_user, account):
            return {"ok": False, "status": "forbidden", "error": "只能确认自己可见账户的执行计划。"}
        if plan.get("status") != "planned":
            return {"ok": False, "error": "只有待演练计划可以人工确认，已拦截或无动作计划只保留审计。"}

        # 计划有效期：过期计划不可确认（市场状态已变，动作建议失效）
        expires_at_ms = plan.get("expires_at_ms")
        if expires_at_ms and int(time.time() * 1000) > int(expires_at_ms):
            return {
                "ok": False,
                "status": "expired",
                "error": "执行计划已过有效期，请重新生成后再确认。",
            }
        # 价格漂移：确认时价格偏离生成时刻超过阈值，同样拒绝
        drift = self._confirm_price_drift_pct(plan)
        if drift is not None and drift > self.max_confirm_price_drift_pct:
            return {
                "ok": False,
                "status": "price_drift",
                "error": (
                    f"当前价格较计划生成时已漂移 {drift:.2f}%"
                    f"（阈值 {self.max_confirm_price_drift_pct:.2f}%），请重新生成计划。"
                ),
            }

        before = deepcopy(plan.get("manual_review") or {})
        reviewed_at = now_iso()
        plan["manual_review"] = {
            "status": "confirmed",
            "reviewed_by": actor,
            "reviewed_at": reviewed_at,
            "note": normalized_note,
        }
        self.plans.save(plan)
        return {
            "ok": True,
            "plan": deepcopy(plan),
            "_audit": {
                "actor": actor,
                "action_type": "CONFIRM_EXECUTION_PLAN",
                "reason": f"人工确认执行计划：{normalized_plan_id}",
                "before_value": before,
                "after_value": {
                    "plan_id": normalized_plan_id,
                    "account_id": plan.get("account_id"),
                    "symbol": plan.get("symbol"),
                    "event_type": plan.get("event_type"),
                    "reviewed_at": reviewed_at,
                    "note": normalized_note,
                },
            },
        }

    def portfolio_stopped(self, strategy: dict[str, Any]) -> bool:
        """组合级回撤：全部已同步账户的合计未实现盈亏触及 max_total_drawdown_pct → 全局 STOP。"""
        body = strategy.get("strategy", strategy)
        limit_pct = float(body.get("risk", {}).get("max_total_drawdown_pct") or 0)
        if limit_pct <= 0:
            return False
        basis = 0.0
        pnl = 0.0
        for snapshot in self.snapshots.all().values():
            if snapshot.get("status") != "synced":
                continue
            equity = float(snapshot.get("total_margin_balance") or snapshot.get("total_wallet_balance") or 0)
            unrealized = float(snapshot.get("total_unrealized_profit") or 0)
            basis += equity - unrealized
            pnl += unrealized
        if basis <= 0:
            return False
        return pnl < -(basis * limit_pct / 100.0)

    def _confirm_price_drift_pct(self, plan: dict[str, Any]) -> float | None:
        if self.symbol_states is None:
            return None
        trigger = plan.get("trigger") or {}
        plan_price = float(trigger.get("mark_price") or 0)
        if plan_price <= 0:
            return None
        state = lookup_plan_state(
            self.symbol_states.all(),
            str(plan.get("account_id", "")),
            str(plan.get("symbol", "")),
        )
        if not state:
            return None
        current_price = float(state.get("last_price") or 0)
        if current_price <= 0:
            return None
        return abs(current_price / plan_price - 1) * 100

    def record_export(
        self,
        *,
        plan_ids: list[Any],
        actor: str,
        actor_user: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not isinstance(plan_ids, list):
            return {"ok": False, "error": "导出计划参数必须是计划 ID 数组。"}
        normalized_ids = [str(item).strip() for item in plan_ids if str(item or "").strip()]
        if not normalized_ids:
            return {"ok": False, "error": "没有可导出的执行计划。"}

        selected_plans = []
        missing = []
        for plan_id in normalized_ids:
            plan = self.plans.get(plan_id)
            if plan:
                selected_plans.append(plan)
            else:
                missing.append(plan_id)
        if missing:
            return {"ok": False, "error": f"执行计划不存在：{', '.join(missing)}"}

        forbidden = [
            plan.get("id")
            for plan in selected_plans
            if not self.permissions.can_access_account(
                actor_user,
                self.accounts.account_by_id(str(plan.get("account_id", ""))),
            )
        ]
        if forbidden:
            return {"ok": False, "status": "forbidden", "error": "只能导出自己可见账户的执行计划。"}

        exported_at = now_iso()
        export_id = f"plan_export_{int(time.time() * 1000)}"
        for plan in selected_plans:
            plan["last_export"] = {
                "id": export_id,
                "exported_by": actor,
                "exported_at": exported_at,
            }
            self.plans.save(plan)

        status_counts = {
            "planned": sum(1 for plan in selected_plans if plan.get("status") == "planned"),
            "blocked": sum(1 for plan in selected_plans if plan.get("status") == "blocked"),
            "no_action": sum(1 for plan in selected_plans if plan.get("status") == "no_action"),
            "confirmed": sum(
                1
                for plan in selected_plans
                if plan.get("manual_review", {}).get("status") == "confirmed"
            ),
        }
        account_ids = sorted({str(plan.get("account_id")) for plan in selected_plans if plan.get("account_id")})
        return {
            "ok": True,
            "export_id": export_id,
            "exported_at": exported_at,
            "plan_count": len(selected_plans),
            "account_ids": account_ids,
            "status_counts": status_counts,
            "_audit": {
                "actor": actor,
                "action_type": "EXPORT_EXECUTION_PLANS",
                "reason": f"导出第一阶段执行计划：{len(selected_plans)} 条。",
                "after_value": {
                    "export_id": export_id,
                    "exported_at": exported_at,
                    "plan_ids": normalized_ids,
                    "account_ids": account_ids,
                    "status_counts": status_counts,
                },
            },
        }


class ExecutionPlanRefreshService:
    def __init__(
        self,
        run_configs: AccountRunConfigService,
        symbol_states: SymbolStateService,
        execution_plans: ExecutionPlanService,
        strategy: dict[str, Any],
        *,
        mock_data_enabled: bool,
    ):
        self.run_configs = run_configs
        self.symbol_states = symbol_states
        self.execution_plans = execution_plans
        self.strategy = strategy
        self.mock_data_enabled = mock_data_enabled

    def refresh(self, account_ids: set[str]) -> list[dict[str, Any]]:
        self.run_configs.ensure_all()
        if not self.mock_data_enabled:
            self.symbol_states.refresh_plan_symbol_states(account_ids=account_ids)
        return self._build(account_ids)

    def refresh_from_states(self, account_ids: set[str]) -> list[dict[str, Any]]:
        """行情 tick 后重建计划：状态已由行情推进，不再用旧快照回写（避免双重计 tick）。"""
        self.run_configs.ensure_all()
        return self._build(account_ids)

    def _build(self, account_ids: set[str]) -> list[dict[str, Any]]:
        result = self.execution_plans.build_for_accounts(
            account_ids=account_ids,
            strategy=self.strategy,
            symbol_states=self.symbol_states.repository.all(),
        )
        return result["new_plans"]
