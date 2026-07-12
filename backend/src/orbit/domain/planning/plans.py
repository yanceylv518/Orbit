from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import uuid4

from orbit.domain.risk.guards import RiskContext, RiskPolicy, evaluate_risk, guard_actions
from orbit.domain.strategy.actions import StrategyAction, StrategyLeg, StrategyPosition, build_strategy_action_set
from orbit.domain.strategy.engine import now_iso, q
from orbit.domain.strategy.exposure import decide_target_exposure, derive_anchor_price
from orbit.domain.strategy.rules.event_rules import EventRuleResult, StrategyEventRules


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def flt(value: Decimal | int | float | str | None) -> float:
    if value is None:
        return 0.0
    return float(value)


DEFAULT_PLAN_TTL_SECONDS = 900


def generate_account_execution_plans(
    account: dict[str, Any],
    run_config: dict[str, Any],
    strategy: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    symbol_states: dict[str, dict[str, Any]] | None = None,
    ttl_seconds: int = DEFAULT_PLAN_TTL_SECONDS,
) -> list[dict[str, Any]]:
    created_at = now_iso()
    created_at_ms = int(time.time() * 1000)
    common = {
        "account_id": account["id"],
        "user_id": account["user_id"],
        "strategy_id": strategy["id"],
        "created_at": created_at,
        "created_at_ms": created_at_ms,
        # 计划有效期：计划是对某一时刻市场状态的动作建议，超时或价格漂移后不可再确认
        "ttl_seconds": int(ttl_seconds),
        "expires_at_ms": created_at_ms + int(ttl_seconds) * 1000,
        "mode": run_config.get("mode", "plan_only"),
    }

    if not run_config.get("enabled", False):
        return [blocked_plan(common, "ACCOUNT_CONFIG_DISABLED", "-", "账户运行配置未启用。")]

    if not snapshot:
        return [blocked_plan(common, "SYNC_REQUIRED", "-", "尚未同步 Binance 账户，无法生成执行计划。")]

    if snapshot.get("status") != "synced":
        return [blocked_plan(
            common,
            "SYNC_REQUIRED",
            "-",
            snapshot.get("error") or f"账户同步状态为 {snapshot.get('status', '-')}",
        )]

    position_mode = snapshot.get("position_mode") or {}
    if position_mode.get("hedge_mode_ok") is False:
        return [blocked_plan(common, "HEDGE_MODE_REQUIRED", "-", "账户未通过 Hedge Mode 检查。")]

    allowed_symbols = normalized_symbols(run_config, strategy)
    positions_by_symbol = group_positions(snapshot.get("positions", []), allowed_symbols)
    if not positions_by_symbol:
        return [no_action_plan(common, "NO_REAL_POSITION", "-", "当前账户没有匹配运行配置的真实持仓。")]

    plans: list[dict[str, Any]] = []
    event_rules = StrategyEventRules(strategy)
    symbol_states = symbol_states or {}
    for symbol in allowed_symbols:
        sides = positions_by_symbol.get(symbol)
        if not sides:
            continue
        plan = plan_symbol(
            common,
            run_config,
            strategy,
            snapshot,
            symbol,
            sides,
            symbol_states.get(symbol),
            event_rules,
        )
        if plan:
            plans.append(plan)

    if not plans:
        plans.append(no_action_plan(common, "NO_TRIGGER", "-", "真实持仓已同步，但当前没有触发利润搬运、仓位恢复或亏损腿减仓条件。"))
    return plans


def plan_symbol(
    common: dict[str, Any],
    run_config: dict[str, Any],
    strategy: dict[str, Any],
    snapshot: dict[str, Any],
    symbol: str,
    sides: dict[str, dict[str, Decimal]],
    symbol_state: dict[str, Any] | None = None,
    event_rules: StrategyEventRules | None = None,
) -> dict[str, Any] | None:
    long = sides.get("LONG", empty_side())
    short = sides.get("SHORT", empty_side())
    mark_price = long["mark_price"] or short["mark_price"]
    if mark_price <= 0:
        return None

    budget = symbol_budget(run_config, strategy, symbol)
    base_position = dec(run_config.get("base_position_usdt", strategy["strategy"].get("base_position_usdt", 0)))
    anchor_price = derive_anchor_price(long["entry_price"], short["entry_price"], mark_price)
    state = plan_state_context(symbol, symbol_state, anchor_price, mark_price, base_position, budget)
    base_price = dec(state.get("base_price")) or anchor_price
    base_qty = dec(state.get("base_qty"))
    if base_qty <= 0 and base_price > 0:
        base_qty = base_position / base_price
    max_single_order = dec(run_config.get("max_single_order_usdt", 0))
    decision = decide_target_exposure(
        price=mark_price,
        base_price=base_price,
        base_qty=base_qty,
        long_qty=long["qty"],
        short_qty=short["qty"],
        strategy=strategy,
    )

    trigger_context = {
        "snapshot_synced_at": snapshot.get("synced_at"),
        "mark_price": flt(mark_price),
        "anchor_price": flt(anchor_price),
        "long_qty": flt(long["qty"]),
        "short_qty": flt(short["qty"]),
        "long_unrealized_pnl": flt(long["pnl"]),
        "short_unrealized_pnl": flt(short["pnl"]),
        "long_notional": flt(long["notional"]),
        "short_notional": flt(short["notional"]),
        "symbol_budget_usdt": flt(budget),
        "base_position_usdt": flt(base_position),
        "plan_state_source": "symbol_state" if symbol_state else "snapshot_inferred",
        "plan_state": str(state.get("state", "BALANCED")),
        "plan_base_price": flt(base_price),
        "plan_base_qty": flt(base_qty),
        "plan_high_since_base": flt(dec(state.get("high_since_base"))),
        "plan_low_since_base": flt(dec(state.get("low_since_base"))),
        "plan_trend_extreme_price": flt(dec(state.get("trend_extreme_price"))),
        "plan_trend_exit_candidate_count": int(state.get("trend_exit_candidate_count", 0)),
        "plan_profit_transfer_count_in_trend": int(state.get("profit_transfer_count_in_trend", 0)),
        "plan_loss_side_reduce_count_in_trend": int(state.get("loss_side_reduce_count_in_trend", 0)),
        "plan_recovery_count_in_trend": int(state.get("recovery_count_in_trend", 0)),
        **decision.context(),
    }
    risk_context = symbol_risk_context(symbol, mark_price, budget, long, short, snapshot)
    risk_policy = RiskPolicy.from_config(strategy, run_config, enforce_plan_only=True)
    risk_state = evaluate_risk(risk_context, risk_policy)
    if risk_state.symbol_stopped:
        trigger_context.update({
            "risk_state": "STOPPED",
            "total_pnl_usdt": flt(risk_state.total_pnl_usdt),
            "drawdown_limit_usdt": flt(risk_state.drawdown_limit_usdt),
        })
        return stop_unwind_plan(
            common, run_config, strategy, symbol, mark_price, long, short,
            trigger_context, risk_context,
        )

    return target_exposure_plan(
        common, run_config, symbol, mark_price, budget, base_position,
        long, short, max_single_order, trigger_context, decision, risk_context, strategy,
        state, event_rules or StrategyEventRules(strategy),
    )


def plan_state_context(
    symbol: str,
    symbol_state: dict[str, Any] | None,
    anchor_price: Decimal,
    mark_price: Decimal,
    base_position: Decimal,
    budget: Decimal,
) -> dict[str, Any]:
    state = dict(symbol_state or {})
    base_price = dec(state.get("base_price")) or anchor_price or mark_price
    base_qty = dec(state.get("base_qty"))
    if base_qty <= 0 and base_price > 0:
        base_qty = base_position / base_price

    state.setdefault("symbol", symbol)
    state.setdefault("state", "BALANCED")
    state["base_price"] = str(base_price)
    state["base_qty"] = str(q(base_qty))
    state["last_price"] = str(mark_price)
    state.setdefault("high_since_base", str(max(base_price, mark_price)))
    state.setdefault("low_since_base", str(min(base_price, mark_price)))
    state.setdefault("trend_extreme_price", str(mark_price))
    state.setdefault("budget_usdt", str(budget))
    state.setdefault("tick_count", 0)
    state.setdefault("profit_transfer_count_in_trend", 0)
    state.setdefault("loss_side_reduce_count_in_trend", 0)
    state.setdefault("recovery_count_in_trend", 0)
    state.setdefault("trend_exit_candidate_count", 0)
    state.setdefault("last_transfer_tick", -999999)
    state.setdefault("last_loss_reduce_tick", -999999)
    state.setdefault("last_transfer_price", None)
    state.setdefault("last_loss_reduce_price", None)
    return state


def target_exposure_plan(
    common: dict[str, Any],
    run_config: dict[str, Any],
    symbol: str,
    price: Decimal,
    budget: Decimal,
    base_position: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
    max_single_order: Decimal,
    trigger_context: dict[str, Any],
    decision: Any,
    risk_context: RiskContext,
    strategy: dict[str, Any],
    state: dict[str, Any],
    event_rules: StrategyEventRules,
) -> dict[str, Any] | None:
    if not decision.has_action:
        return None

    rule_result = event_rules.evaluate(decision, state, price)
    if not rule_result.allowed:
        return rule_blocked_plan(common, symbol, decision, trigger_context, rule_result)

    action_set = build_strategy_action_set(
        decision,
        strategy_position(symbol, price, budget, base_position, long, short),
        strategy,
    )
    if action_set is None:
        return None

    return build_plan(
        common,
        symbol,
        action_set.event_type,
        action_set.direction,
        action_set.reason,
        [build_strategy_action(action, price, max_single_order) for action in action_set.actions],
        {
            **trigger_context,
            "event_rule": rule_result.code,
            **rule_result.context,
            **action_set.trigger,
        },
        run_config,
        risk_context,
        strategy,
    )


def stop_unwind_plan(
    common: dict[str, Any],
    run_config: dict[str, Any],
    strategy: dict[str, Any],
    symbol: str,
    price: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
    trigger_context: dict[str, Any],
    risk_context: RiskContext,
) -> dict[str, Any] | None:
    actions = []
    reason = "单币种回撤触发 STOPPED：拆对冲全平，等待人工复核后恢复。"
    if long["qty"] > 0:
        actions.append(build_action(
            "REDUCE_LONG", "LONG", long["qty"], price, Decimal("0"), reason,
            risk_intent="STOP_UNWIND", ignore_max_single_order=True,
        ))
    if short["qty"] > 0:
        actions.append(build_action(
            "REDUCE_SHORT", "SHORT", short["qty"], price, Decimal("0"), reason,
            risk_intent="STOP_UNWIND", ignore_max_single_order=True,
        ))
    if not actions:
        return None

    return build_plan(
        common, symbol, "MAX_SYMBOL_DRAWDOWN_STOP", "STOPPED", reason,
        actions, trigger_context, run_config, risk_context, strategy,
    )

def build_plan(
    common: dict[str, Any],
    symbol: str,
    event_type: str,
    direction: str,
    reason: str,
    actions: list[dict[str, Any]],
    trigger_context: dict[str, Any],
    run_config: dict[str, Any],
    risk_context: RiskContext,
    strategy: dict[str, Any],
) -> dict[str, Any]:
    result = guard_actions(actions, risk_context, RiskPolicy.from_config(strategy, run_config, enforce_plan_only=True))
    actions = result.actions
    blocked = [item for item in actions if item.get("status") == "blocked"]
    planned = [item for item in actions if item.get("status") == "planned"]
    return {
        **common,
        "id": f"plan_{uuid4().hex[:16]}",
        "symbol": symbol,
        "event_type": event_type,
        "direction": direction,
        "reason": reason,
        "status": "planned" if planned else "blocked",
        "actions": actions,
        "risk_checks": result.checks,
        "trigger": trigger_context,
    }


def rule_blocked_plan(
    common: dict[str, Any],
    symbol: str,
    decision: Any,
    trigger_context: dict[str, Any],
    rule_result: EventRuleResult,
) -> dict[str, Any]:
    return {
        **common,
        "id": f"plan_{uuid4().hex[:16]}",
        "symbol": symbol,
        "event_type": decision.event_type,
        "direction": decision.direction,
        "reason": rule_result.reason,
        "status": "blocked",
        "actions": [],
        "risk_checks": [{
            "name": rule_result.code,
            "ok": False,
            "message": rule_result.reason,
            **rule_result.context,
        }],
        "trigger": {
            **trigger_context,
            "event_rule": rule_result.code,
            **rule_result.context,
        },
    }


def build_action(
    action: str,
    position_side: str,
    qty: Decimal,
    price: Decimal,
    max_single_order: Decimal,
    reason: str,
    *,
    risk_intent: str = "STRATEGY",
    ignore_max_single_order: bool = False,
) -> dict[str, Any]:
    qty = max(Decimal("0"), qty)
    notional = qty * price
    capped = False
    if not ignore_max_single_order and max_single_order > 0 and notional > max_single_order:
        qty = max_single_order / price
        notional = max_single_order
        capped = True
    side = "BUY" if action in ("ADD_LONG", "REDUCE_SHORT") else "SELL"
    return {
        "action": action,
        "side": side,
        "position_side": position_side,
        "order_type": "MARKET_PREVIEW",
        "quantity": flt(q(qty)),
        "notional_usdt": flt(q(notional)),
        "reduce_only": action.startswith("REDUCE_"),
        "status": "planned",
        "capped_by_max_single_order": capped,
        "risk_intent": risk_intent,
        "reason": reason,
    }


def build_strategy_action(action: StrategyAction, price: Decimal, max_single_order: Decimal) -> dict[str, Any]:
    return build_action(
        action.action,
        action.position_side,
        action.quantity,
        price,
        max_single_order,
        action.reason,
        risk_intent=action.risk_intent,
    )


def blocked_plan(common: dict[str, Any], event_type: str, symbol: str, reason: str) -> dict[str, Any]:
    return {
        **common,
        "id": f"plan_{uuid4().hex[:16]}",
        "symbol": symbol,
        "event_type": event_type,
        "direction": "-",
        "reason": reason,
        "status": "blocked",
        "actions": [],
        "risk_checks": [{"name": event_type, "ok": False, "message": reason}],
        "trigger": {},
    }


def no_action_plan(common: dict[str, Any], event_type: str, symbol: str, reason: str) -> dict[str, Any]:
    return {
        **common,
        "id": f"plan_{uuid4().hex[:16]}",
        "symbol": symbol,
        "event_type": event_type,
        "direction": "-",
        "reason": reason,
        "status": "no_action",
        "actions": [],
        "risk_checks": [{"name": "no_action", "ok": True, "message": reason}],
        "trigger": {},
    }


def normalized_symbols(run_config: dict[str, Any], strategy: dict[str, Any]) -> list[str]:
    symbols = run_config.get("symbols") or strategy.get("symbols", [])
    return [str(symbol).upper().strip() for symbol in symbols if str(symbol).strip()]


def symbol_budget(run_config: dict[str, Any], strategy: dict[str, Any], symbol: str) -> Decimal:
    budgets = run_config.get("symbol_budget_usdt") or strategy.get("symbol_budget_usdt", {})
    return dec(budgets.get(symbol, strategy.get("strategy", {}).get("base_position_usdt", 0)))


def symbol_risk_context(
    symbol: str,
    price: Decimal,
    budget: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
    snapshot: dict[str, Any],
) -> RiskContext:
    return RiskContext(
        symbol=symbol,
        price=price,
        long_qty=long["qty"],
        short_qty=short["qty"],
        budget_usdt=budget,
        realized_pnl=dec(snapshot.get("realized_pnl")),
        long_unrealized_pnl=long["pnl"],
        short_unrealized_pnl=short["pnl"],
    )


def strategy_position(
    symbol: str,
    price: Decimal,
    budget: Decimal,
    base_position: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
) -> StrategyPosition:
    return StrategyPosition(
        symbol=symbol,
        price=price,
        budget_usdt=budget,
        base_position_usdt=base_position,
        long=StrategyLeg(
            side="LONG",
            qty=long["qty"],
            entry_price=long["entry_price"],
            mark_price=price,
            unrealized_pnl=long["pnl"],
            notional=long["notional"],
        ),
        short=StrategyLeg(
            side="SHORT",
            qty=short["qty"],
            entry_price=short["entry_price"],
            mark_price=price,
            unrealized_pnl=short["pnl"],
            notional=short["notional"],
        ),
    )


def group_positions(positions: list[dict[str, Any]], allowed_symbols: list[str]) -> dict[str, dict[str, dict[str, Decimal]]]:
    allowed = set(allowed_symbols)
    grouped: dict[str, dict[str, dict[str, Decimal]]] = {}
    for item in positions:
        symbol = str(item.get("symbol", "")).upper()
        if allowed and symbol not in allowed:
            continue
        qty = dec(item.get("position_amt"))
        if qty == 0:
            continue
        position_side = str(item.get("position_side") or "BOTH").upper()
        if position_side == "BOTH":
            position_side = "LONG" if qty > 0 else "SHORT"
        side = grouped.setdefault(symbol, {})
        side[position_side] = {
            "qty": abs(qty),
            "entry_price": dec(item.get("entry_price")),
            "mark_price": dec(item.get("mark_price")),
            "pnl": dec(item.get("unrealized_profit")),
            "notional": abs(dec(item.get("notional"))),
        }
    return grouped


def empty_side() -> dict[str, Decimal]:
    return {
        "qty": Decimal("0"),
        "entry_price": Decimal("0"),
        "mark_price": Decimal("0"),
        "pnl": Decimal("0"),
        "notional": Decimal("0"),
    }
