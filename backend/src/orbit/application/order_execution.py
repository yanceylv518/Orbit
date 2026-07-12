from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Callable

from orbit.application.execution_plans import ExecutionPlanService
from orbit.application.permissions import PermissionPolicy
from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.execution_plan_repository import ExecutionPlanRepository
from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.domain.strategy.engine import now_iso


DEFAULT_LIVE_CONFIRM_PHRASE = "I UNDERSTAND LIVE TRADING"


class OrderExecutionService:
    """live 下单通道。默认关闭；打开后每一单仍需逐闸通过：

    G1 runtime.live_trading_enabled = true（全局开关，默认 false）
    G2 操作者必须是管理员
    G3 计划存在、状态 planned、已人工确认
    G4 计划未过期且价格漂移复检通过（复用 TTL 双闸）
    G5 账户运行配置 mode=live 且 enabled
    G6 账户 dry_run=false 且状态 active
    G7 请求携带的确认短语与 runtime.live_confirm_phrase 完全一致
    G8 第一版只放行 reduce_only 动作（任何 ADD_* 拒绝执行）
    """

    def __init__(
        self,
        permissions: PermissionPolicy,
        accounts: AccountRepository,
        run_configs: RunConfigRepository,
        plans: ExecutionPlanRepository,
        plan_service: ExecutionPlanService,
        gateway_factory: Callable[[dict[str, Any]], Any],
        *,
        live_trading_enabled: bool = False,
        live_confirm_phrase: str = DEFAULT_LIVE_CONFIRM_PHRASE,
    ):
        self.permissions = permissions
        self.accounts = accounts
        self.run_configs = run_configs
        self.plans = plans
        self.plan_service = plan_service
        self.gateway_factory = gateway_factory
        self.live_trading_enabled = bool(live_trading_enabled)
        self.live_confirm_phrase = str(live_confirm_phrase)

    def execute(
        self,
        *,
        plan_id: str,
        actor: str,
        actor_user: dict[str, Any] | None,
        confirm_phrase: str,
    ) -> dict[str, Any]:
        # G1 全局开关
        if not self.live_trading_enabled:
            return {"ok": False, "status": "disabled", "error": "live 下单通道未开启（runtime.live_trading_enabled=false）。"}
        # G2 管理员
        if not self.permissions.is_admin(actor_user):
            return {"ok": False, "status": "forbidden", "error": "只有管理员可以执行 live 下单。"}

        plan = self.plans.get(str(plan_id or "").strip())
        # G3 计划状态
        if not plan:
            return {"ok": False, "error": f"执行计划不存在：{plan_id}"}
        if plan.get("status") != "planned":
            return {"ok": False, "error": "只有待演练计划可以执行。"}
        if plan.get("manual_review", {}).get("status") != "confirmed":
            return {"ok": False, "status": "unconfirmed", "error": "计划必须先人工确认后才能执行。"}
        if plan.get("execution", {}).get("status") in ("executed", "partial"):
            return {"ok": False, "status": "already_executed", "error": "该计划已执行过，重新生成后再操作。"}

        # G4 有效期与漂移复检（与确认同一语义）
        expires_at_ms = plan.get("expires_at_ms")
        if expires_at_ms and int(time.time() * 1000) > int(expires_at_ms):
            return {"ok": False, "status": "expired", "error": "计划已过有效期，禁止执行。"}
        drift = self.plan_service._confirm_price_drift_pct(plan)
        if drift is not None and drift > self.plan_service.max_confirm_price_drift_pct:
            return {"ok": False, "status": "price_drift", "error": f"价格已漂移 {drift:.2f}%，禁止执行，请重新生成计划。"}

        account = self.accounts.account_by_id(str(plan.get("account_id", "")))
        if not account:
            return {"ok": False, "error": "账户不存在。"}
        # G5 运行配置
        run_config = next(
            (item for item in self.run_configs.all() if item.get("account_id") == account.get("id")),
            None,
        )
        if not run_config or not run_config.get("enabled") or run_config.get("mode") != "live":
            return {"ok": False, "status": "mode", "error": "账户运行配置必须 enabled 且 mode=live。"}
        # G6 账户实盘属性
        if account.get("dry_run", True):
            return {"ok": False, "status": "dry_run", "error": "账户仍为 dry_run=true，禁止真实下单。"}
        if account.get("status") != "active":
            return {"ok": False, "status": "account_status", "error": "账户状态非 active，禁止下单。"}
        # G7 确认短语
        if str(confirm_phrase or "") != self.live_confirm_phrase:
            return {"ok": False, "status": "confirm_phrase", "error": "确认短语不正确。"}

        # G8 只放行 reduce_only 动作
        actions = [item for item in plan.get("actions", []) if item.get("status") == "planned"]
        if not actions:
            return {"ok": False, "error": "计划没有可执行的动作。"}
        adds = [item for item in actions if not item.get("reduce_only")]
        if adds:
            return {
                "ok": False,
                "status": "reduce_only_required",
                "error": "第一版 live 只允许 reduce-only 动作，含加仓动作的计划禁止执行。",
            }

        gateway = self.gateway_factory(account)
        fills: list[dict[str, Any]] = []
        error: str | None = None
        for action in actions:
            params = {
                "symbol": plan.get("symbol"),
                "side": action.get("side"),
                "positionSide": action.get("position_side"),
                "type": "MARKET",
                "quantity": action.get("quantity"),
                "reduceOnly": "true",
                "newClientOrderId": f"orbit_{plan.get('id', '')[:20]}_{len(fills)}",
            }
            try:
                response = gateway.place_order(params)
                fills.append({"action": action.get("action"), "params": params, "response": response})
            except Exception as exc:  # 单个动作失败即停止后续，保留已成交记录
                error = f"{action.get('action')}: {exc}"
                break

        executed_at = now_iso()
        status = "executed" if error is None else ("partial" if fills else "failed")
        plan["execution"] = {
            "status": status,
            "executed_by": actor,
            "executed_at": executed_at,
            "fills": fills,
            "error": error,
        }
        self.plans.save(plan)
        return {
            "ok": error is None,
            "status": status,
            "fills": deepcopy(fills),
            "error": error,
            "_audit": {
                "actor": actor,
                "action_type": "EXECUTE_LIVE_PLAN",
                "reason": f"live 执行计划 {plan.get('id')}：{status}，{len(fills)} 笔成交。",
                "after_value": {
                    "plan_id": plan.get("id"),
                    "account_id": plan.get("account_id"),
                    "symbol": plan.get("symbol"),
                    "status": status,
                    "fill_count": len(fills),
                    "error": error,
                },
            },
        }
