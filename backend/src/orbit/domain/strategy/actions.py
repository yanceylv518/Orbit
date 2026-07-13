from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any

from orbit.domain.strategy.exposure import TargetExposureDecision, q, strategy_body


ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
PRICE_STEP = Decimal("0.000000000001")


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def pct(value: Any) -> Decimal:
    return dec(value) / HUNDRED


@dataclass(frozen=True)
class StrategyLeg:
    side: str
    qty: Decimal
    entry_price: Decimal
    mark_price: Decimal
    unrealized_pnl: Decimal
    notional: Decimal = ZERO


@dataclass(frozen=True)
class StrategyPosition:
    symbol: str
    price: Decimal
    budget_usdt: Decimal
    base_position_usdt: Decimal
    long: StrategyLeg
    short: StrategyLeg


@dataclass(frozen=True)
class StrategyAction:
    action: str
    position_side: str
    quantity: Decimal
    event_role: str
    reason: str
    risk_intent: str = "STRATEGY"


@dataclass(frozen=True)
class StrategyActionSet:
    event_type: str
    direction: str
    reason: str
    actions: list[StrategyAction]
    sizing: dict[str, str]
    trigger: dict[str, str]


@dataclass(frozen=True)
class ReducePreview:
    gross_realized: Decimal
    fee: Decimal
    net_realized: Decimal


def build_strategy_action_set(
    decision: TargetExposureDecision,
    position: StrategyPosition,
    strategy: dict[str, Any],
) -> StrategyActionSet | None:
    if not decision.has_action:
        return None

    event_type = str(decision.event_type)
    events = strategy_body(strategy)["events"]
    if event_type.startswith("PROFIT_TRANSFER"):
        return inverse_skew_actions(decision, position, strategy)
    if event_type.startswith("LOSS_SIDE_REDUCTION"):
        return trend_reduction_actions(decision, position, events["loss_side_reduction"])
    if event_type.startswith("POSITION_REBUILD"):
        return position_rebuild_actions(decision, position, events["position_recovery"])
    if event_type.startswith("POSITION_RECOVERY"):
        return exposure_recovery_actions(decision, position)
    return None


def inverse_skew_actions(
    decision: TargetExposureDecision,
    position: StrategyPosition,
    strategy: dict[str, Any],
) -> StrategyActionSet | None:
    body = strategy_body(strategy)
    cfg = body["events"]["profit_transfer"]
    costs = body["costs"]
    min_profit = position.budget_usdt * pct(cfg["trigger"]["min_profit_pct_of_symbol_budget"])
    reduce_ratio = dec(cfg["sizing"]["reduce_profit_side_ratio"])
    add_ratio = dec(cfg["sizing"]["use_realized_profit_ratio_for_loss_side"])
    max_add = position.base_position_usdt * dec(cfg["sizing"]["max_add_loss_side_ratio_of_base_position"])
    delta_qty = abs(decision.delta_qty)

    if decision.delta_qty < 0:
        profit = position.long
        reduce_action = "REDUCE_LONG"
        add_action = "ADD_SHORT"
        target_side = "SHORT"
        profit_side = "LONG"
    else:
        profit = position.short
        reduce_action = "REDUCE_SHORT"
        add_action = "ADD_LONG"
        target_side = "LONG"
        profit_side = "SHORT"

    if profit.qty <= ZERO or profit.unrealized_pnl < min_profit:
        return None

    reduce_qty = q(min(delta_qty / Decimal("2"), profit.qty * reduce_ratio, profit.qty))
    if reduce_qty <= ZERO:
        return None

    projected = preview_reduce(profit, reduce_action, reduce_qty, position.price, costs)
    add_notional_budget = min(max(projected.net_realized, ZERO) * add_ratio, max_add)
    add_qty = max(ZERO, delta_qty - reduce_qty)
    if position.price > ZERO:
        add_qty = q(min(add_qty, add_notional_budget / position.price))
    else:
        add_qty = ZERO

    add_leg_roundtrip_cost = estimate_add_leg_roundtrip_cost(add_qty, position.price, costs)
    min_net_profit = dec(cfg["sizing"]["min_net_profit_usdt"])
    required_net_profit = min_net_profit
    if bool(cfg["sizing"].get("require_add_leg_roundtrip_coverage", False)):
        required_net_profit += add_leg_roundtrip_cost
    if projected.net_realized < required_net_profit:
        return None

    actions = [
        StrategyAction(
            action=reduce_action,
            position_side=profit_side,
            quantity=reduce_qty,
            event_role="REDUCE_PROFIT_SIDE",
            reason=f"profit_transfer_reduce_{profit_side.lower()}_to_target_net_{target_side.lower()}",
        )
    ]
    if add_qty > ZERO:
        actions.append(StrategyAction(
            action=add_action,
            position_side=target_side,
            quantity=add_qty,
            event_role="ADD_LOSS_SIDE",
            reason=f"profit_transfer_add_{target_side.lower()}_to_target_net_{target_side.lower()}",
        ))

    return StrategyActionSet(
        event_type=str(decision.event_type),
        direction=decision.direction,
        reason=decision.reason,
        actions=actions,
        sizing={
            "reduce_qty": str(reduce_qty),
            "add_qty": str(add_qty),
            "projected_net_realized": str(projected.net_realized),
            "estimated_add_leg_roundtrip_cost": str(add_leg_roundtrip_cost),
            "required_net_profit": str(required_net_profit),
            "delta_to_target_qty": str(decision.delta_qty),
        },
        trigger={
            "profit_side": profit_side,
            "profit_pnl": str(profit.unrealized_pnl),
        },
    )


def trend_reduction_actions(
    decision: TargetExposureDecision,
    position: StrategyPosition,
    cfg: dict[str, Any],
) -> StrategyActionSet | None:
    reduce_ratio = dec(cfg["sizing"]["reduce_loss_side_ratio"])
    delta_qty = abs(decision.delta_qty)
    if decision.delta_qty > ZERO:
        side = position.short
        action = "REDUCE_SHORT"
        loss_side = "SHORT"
    else:
        side = position.long
        action = "REDUCE_LONG"
        loss_side = "LONG"

    reduce_qty = q(min(delta_qty, side.qty * reduce_ratio, side.qty))
    if reduce_qty <= ZERO:
        return None

    return StrategyActionSet(
        event_type=str(decision.event_type),
        direction=decision.direction,
        reason=decision.reason,
        actions=[StrategyAction(
            action=action,
            position_side=loss_side,
            quantity=reduce_qty,
            event_role="LOSS_SIDE_REDUCTION",
            reason="confirmed_trend_reduce_loss_side_to_target_exposure",
        )],
        sizing={
            "reduce_qty": str(reduce_qty),
            "delta_to_target_qty": str(decision.delta_qty),
        },
        trigger={"loss_side": loss_side},
    )


def exposure_recovery_actions(
    decision: TargetExposureDecision,
    position: StrategyPosition,
) -> StrategyActionSet | None:
    delta_qty = abs(decision.delta_qty)
    if decision.delta_qty > ZERO:
        side = position.short
        action = "REDUCE_SHORT"
        position_side = "SHORT"
    else:
        side = position.long
        action = "REDUCE_LONG"
        position_side = "LONG"

    reduce_qty = q(min(delta_qty, side.qty))
    if reduce_qty <= ZERO:
        return None

    return StrategyActionSet(
        event_type=str(decision.event_type),
        direction=decision.direction,
        reason=decision.reason,
        actions=[StrategyAction(
            action=action,
            position_side=position_side,
            quantity=reduce_qty,
            event_role="POSITION_RECOVERY",
            reason="recover_net_exposure_to_zero",
        )],
        sizing={
            "reduce_qty": str(reduce_qty),
            "delta_to_target_qty": str(decision.delta_qty),
        },
        trigger={},
    )


def position_rebuild_actions(
    decision: TargetExposureDecision,
    position: StrategyPosition,
    cfg: dict[str, Any],
) -> StrategyActionSet | None:
    max_ratio = dec(cfg["sizing"].get("max_restore_per_tick_ratio", 1))
    per_side_cap = q(decision.base_qty * max_ratio)
    if per_side_cap <= ZERO:
        per_side_cap = q(decision.base_qty)

    target_long = decision.target_long_qty if decision.target_long_qty is not None else position.long.qty
    target_short = decision.target_short_qty if decision.target_short_qty is not None else position.short.qty
    add_long_qty = q(min(max(ZERO, target_long - position.long.qty), per_side_cap))
    add_short_qty = q(min(max(ZERO, target_short - position.short.qty), per_side_cap))

    actions: list[StrategyAction] = []
    if add_long_qty > ZERO:
        actions.append(StrategyAction(
            action="ADD_LONG",
            position_side="LONG",
            quantity=add_long_qty,
            event_role="POSITION_REBUILD",
            reason="rebuild_long_leg_to_base_position",
        ))
    if add_short_qty > ZERO:
        actions.append(StrategyAction(
            action="ADD_SHORT",
            position_side="SHORT",
            quantity=add_short_qty,
            event_role="POSITION_REBUILD",
            reason="rebuild_short_leg_to_base_position",
        ))

    if not actions:
        return None

    return StrategyActionSet(
        event_type=str(decision.event_type),
        direction=decision.direction,
        reason=decision.reason,
        actions=actions,
        sizing={
            "add_long_qty": str(add_long_qty),
            "add_short_qty": str(add_short_qty),
            "target_long_qty": str(target_long),
            "target_short_qty": str(target_short),
            "per_side_cap_qty": str(per_side_cap),
        },
        trigger={
            "current_long_qty": str(position.long.qty),
            "current_short_qty": str(position.short.qty),
        },
    )


def preview_reduce(
    leg: StrategyLeg,
    action: str,
    qty: Decimal,
    price: Decimal,
    costs: dict[str, Any],
) -> ReducePreview:
    fill = fill_price(price, action, costs)
    gross = (fill - leg.entry_price) * qty if leg.side == "LONG" else (leg.entry_price - fill) * qty
    notional = fill * qty
    fee = notional * dec(costs["taker_fee_rate"])
    return ReducePreview(
        gross_realized=gross,
        fee=fee,
        net_realized=gross - fee,
    )


def estimate_add_leg_roundtrip_cost(
    add_qty: Decimal,
    price: Decimal,
    costs: dict[str, Any],
) -> Decimal:
    if add_qty <= ZERO or price <= ZERO:
        return ZERO
    add_notional = add_qty * price
    expected_roundtrip_rate = (
        dec(costs["taker_fee_rate"]) * Decimal("2")
        + dec(costs["slippage_bps"]) / Decimal("10000")
    )
    return q(add_notional * expected_roundtrip_rate)


def fill_price(price: Decimal, action: str, costs: dict[str, Any]) -> Decimal:
    slip = dec(costs["slippage_bps"]) / Decimal("10000")
    if action in ("ADD_LONG", "REDUCE_SHORT"):
        return (price * (ONE + slip)).quantize(PRICE_STEP, rounding=ROUND_DOWN)
    return (price * (ONE - slip)).quantize(PRICE_STEP, rounding=ROUND_DOWN)
