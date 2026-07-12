from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


ZERO = Decimal("0")
HUNDRED = Decimal("100")


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def pct(value: Any) -> Decimal:
    return dec(value) / HUNDRED


def flt(value: Decimal | int | float | str | None) -> float:
    if value is None:
        return 0.0
    return float(value)


@dataclass(frozen=True)
class RiskContext:
    symbol: str
    price: Decimal
    long_qty: Decimal
    short_qty: Decimal
    budget_usdt: Decimal
    realized_pnl: Decimal = ZERO
    long_unrealized_pnl: Decimal = ZERO
    short_unrealized_pnl: Decimal = ZERO

    @property
    def net_qty(self) -> Decimal:
        return self.long_qty - self.short_qty

    @property
    def gross_qty(self) -> Decimal:
        return self.long_qty + self.short_qty

    @property
    def gross_exposure_usdt(self) -> Decimal:
        return self.gross_qty * self.price

    @property
    def total_pnl_usdt(self) -> Decimal:
        return self.realized_pnl + self.long_unrealized_pnl + self.short_unrealized_pnl


@dataclass(frozen=True)
class RiskPolicy:
    max_symbol_drawdown_pct: Decimal
    max_gross_exposure_ratio: Decimal
    enforce_plan_only: bool = False
    mode: str | None = None
    allow_reduce_only: bool = False
    allow_add_position: bool = True

    @classmethod
    def from_config(
        cls,
        strategy: dict[str, Any],
        run_config: dict[str, Any] | None = None,
        *,
        enforce_plan_only: bool = False,
    ) -> "RiskPolicy":
        body = strategy.get("strategy", strategy)
        risk = body.get("risk", {})
        run_config = run_config or {}
        has_run_config = bool(run_config)
        return cls(
            max_symbol_drawdown_pct=dec(risk.get("max_symbol_drawdown_pct")),
            max_gross_exposure_ratio=dec(risk.get("max_gross_exposure_ratio")),
            enforce_plan_only=enforce_plan_only,
            mode=str(run_config.get("mode", "")) if has_run_config else None,
            allow_reduce_only=bool(run_config.get("allow_reduce_only", True)) if has_run_config else False,
            allow_add_position=bool(run_config.get("allow_add_position", False)) if has_run_config else True,
        )


@dataclass(frozen=True)
class RiskState:
    gross_exposure_usdt: Decimal
    gross_limit_usdt: Decimal
    gross_exceeded: bool
    total_pnl_usdt: Decimal
    drawdown_limit_usdt: Decimal
    symbol_stopped: bool


@dataclass(frozen=True)
class RiskGuardResult:
    actions: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    state: RiskState

    @property
    def stopped(self) -> bool:
        return self.state.symbol_stopped

    @property
    def blocked_actions(self) -> list[dict[str, Any]]:
        return [item for item in self.actions if item.get("status") == "blocked"]

    @property
    def planned_actions(self) -> list[dict[str, Any]]:
        return [item for item in self.actions if item.get("status") == "planned"]


def evaluate_risk(context: RiskContext, policy: RiskPolicy) -> RiskState:
    gross_limit = context.budget_usdt * policy.max_gross_exposure_ratio
    gross_exceeded = policy.max_gross_exposure_ratio > ZERO and context.gross_exposure_usdt > gross_limit
    drawdown_limit = context.budget_usdt * pct(policy.max_symbol_drawdown_pct)
    symbol_stopped = policy.max_symbol_drawdown_pct > ZERO and context.total_pnl_usdt < -drawdown_limit
    return RiskState(
        gross_exposure_usdt=context.gross_exposure_usdt,
        gross_limit_usdt=gross_limit,
        gross_exceeded=gross_exceeded,
        total_pnl_usdt=context.total_pnl_usdt,
        drawdown_limit_usdt=drawdown_limit,
        symbol_stopped=symbol_stopped,
    )


def guard_actions(
    actions: list[dict[str, Any]],
    context: RiskContext,
    policy: RiskPolicy,
) -> RiskGuardResult:
    state = evaluate_risk(context, policy)
    guarded: list[dict[str, Any]] = []
    projected_long = context.long_qty
    projected_short = context.short_qty

    for action in actions:
        item = dict(action)
        name = str(item.get("action", ""))
        qty = dec(item.get("quantity"))
        notional = dec(item.get("notional_usdt")) or qty * context.price
        risk_intent = str(item.get("risk_intent", "STRATEGY"))
        block_reason = ""
        block_code = ""

        if qty <= ZERO or notional <= ZERO:
            block_code = "INVALID_SIZE"
            block_reason = "计划数量或名义金额必须大于 0。"
        elif policy.enforce_plan_only and policy.mode != "plan_only":
            block_code = "PLAN_ONLY_REQUIRED"
            block_reason = "第一阶段仅允许 plan_only 模式生成计划。"
        elif state.symbol_stopped and risk_intent != "STOP_UNWIND":
            block_code = "SYMBOL_STOPPED"
            block_reason = "单币种回撤已触发 STOPPED，普通策略动作被终止。"
        elif is_add_action(name) and (policy.allow_reduce_only or not policy.allow_add_position):
            block_code = "ADD_POSITION_DISABLED"
            block_reason = "当前账户运行配置禁止新增仓位。"
        elif state.gross_exceeded and is_add_action(name):
            block_code = "ONLY_REDUCE"
            block_reason = "当前 gross 已超过上限，只允许降低 gross 的动作。"
        elif is_reduce_action(name) and not has_reducible_qty(name, qty, projected_long, projected_short):
            block_code = "REDUCE_SIZE_EXCEEDS_POSITION"
            block_reason = "减仓数量超过当前可减仓位。"
        else:
            next_long, next_short = project_position(name, qty, projected_long, projected_short)
            projected_gross = (next_long + next_short) * context.price
            if is_add_action(name) and policy.max_gross_exposure_ratio > ZERO and projected_gross > state.gross_limit_usdt:
                block_code = "MAX_GROSS_EXPOSURE"
                block_reason = "执行后 gross 将超过单币种上限。"
            else:
                item["status"] = "planned"
                projected_long, projected_short = next_long, next_short

        if block_reason:
            item["status"] = "blocked"
            item["block_code"] = block_code
            item["block_reason"] = block_reason
        guarded.append(item)

    blocked = [item for item in guarded if item.get("status") == "blocked"]
    checks = risk_checks(state, policy, guarded, blocked)
    return RiskGuardResult(actions=guarded, checks=checks, state=state)


def risk_checks(
    state: RiskState,
    policy: RiskPolicy,
    actions: list[dict[str, Any]],
    blocked: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if policy.enforce_plan_only:
        checks.append({
            "name": "plan_only",
            "ok": policy.mode == "plan_only",
            "message": "第一阶段只生成执行计划，不直接下单。",
        })
    checks.extend([
        {
            "name": "symbol_drawdown_stop",
            "ok": not state.symbol_stopped,
            "message": (
                "单币种回撤触发 STOPPED，必须拆对冲全平。"
                if state.symbol_stopped
                else "单币种回撤未触发 STOPPED。"
            ),
            "current_pnl_usdt": flt(state.total_pnl_usdt),
            "drawdown_limit_usdt": flt(state.drawdown_limit_usdt),
        },
        {
            "name": "gross_limit",
            "ok": not state.gross_exceeded,
            "message": (
                "gross 超过上限，进入 ONLY_REDUCE。"
                if state.gross_exceeded
                else "gross 未超过单币种上限。"
            ),
            "gross_exposure_usdt": flt(state.gross_exposure_usdt),
            "gross_limit_usdt": flt(state.gross_limit_usdt),
        },
        {
            "name": "add_position_guard",
            "ok": not any(item.get("block_code") == "ADD_POSITION_DISABLED" for item in actions),
            "message": "新增仓位动作必须显式放行。",
        },
        {
            "name": "blocked_actions",
            "ok": not blocked,
            "message": f"{len(blocked)} 个动作被风控拦截。",
        },
    ])
    return checks


def is_add_action(action: str) -> bool:
    return action.startswith("ADD_")


def is_reduce_action(action: str) -> bool:
    return action.startswith("REDUCE_")


def has_reducible_qty(action: str, qty: Decimal, long_qty: Decimal, short_qty: Decimal) -> bool:
    if action == "REDUCE_LONG":
        return qty <= long_qty
    if action == "REDUCE_SHORT":
        return qty <= short_qty
    return True


def project_position(
    action: str,
    qty: Decimal,
    long_qty: Decimal,
    short_qty: Decimal,
) -> tuple[Decimal, Decimal]:
    if action == "ADD_LONG":
        return long_qty + qty, short_qty
    if action == "ADD_SHORT":
        return long_qty, short_qty + qty
    if action == "REDUCE_LONG":
        return max(ZERO, long_qty - qty), short_qty
    if action == "REDUCE_SHORT":
        return long_qty, max(ZERO, short_qty - qty)
    return long_qty, short_qty
