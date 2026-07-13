from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any
from uuid import uuid4

from orbit.domain.risk.guards import RiskContext, RiskGuardResult, RiskPolicy, RiskState, evaluate_risk, guard_actions
from orbit.domain.strategy.actions import StrategyAction, StrategyActionSet, StrategyLeg, StrategyPosition, build_strategy_action_set
from orbit.domain.strategy.exposure import TargetExposureDecision, decide_target_exposure
from orbit.domain.strategy.lifecycle import StrategyLifecycle
from orbit.domain.strategy.regime import RegimeGate, RegimeGateResult
from orbit.domain.strategy.rules.event_rules import EventRuleResult, StrategyEventRules


QTY_STEP = Decimal("0.00000001")
MONEY_STEP = Decimal("0.00000001")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def d(value: Any) -> Decimal:
    return Decimal(str(value))


def pct(value: Decimal) -> Decimal:
    return value / Decimal("100")


def q(value: Decimal, step: Decimal = MONEY_STEP) -> Decimal:
    return value.quantize(step, rounding=ROUND_DOWN)


def f(value: Decimal | int | float | str | None) -> float:
    if value is None:
        return 0.0
    return float(value)


class EventEngine:
    def __init__(self, strategy_config: dict[str, Any]):
        self.config = strategy_config
        self.costs = strategy_config["strategy"]["costs"]
        self.risk = strategy_config["strategy"]["risk"]
        self.events = strategy_config["strategy"]["events"]
        self.event_rules = StrategyEventRules(strategy_config)
        self.lifecycle = StrategyLifecycle(strategy_config)
        self.regime_gate = RegimeGate(strategy_config)
        self.base_position_usdt = d(strategy_config["strategy"]["base_position_usdt"])

    def initialize_symbol(self, symbol: str, price: Decimal, budget_usdt: Decimal) -> dict[str, Any]:
        qty = q(self.base_position_usdt / price, QTY_STEP)
        return {
            "symbol": symbol,
            "state": "BALANCED",
            "base_price": str(price),
            "high_since_base": str(price),
            "low_since_base": str(price),
            "trend_extreme_price": str(price),
            "last_price": str(price),
            "base_qty": str(qty),
            "long_qty": str(qty),
            "short_qty": str(qty),
            "long_entry_price": str(price),
            "short_entry_price": str(price),
            "budget_usdt": str(budget_usdt),
            "realized_pnl": "0",
            "long_unrealized_pnl": "0",
            "short_unrealized_pnl": "0",
            "fee_total": "0",
            "slippage_total": "0",
            "funding_total": "0",
            "profit_transfer_count_in_trend": 0,
            "loss_side_reduce_count_in_trend": 0,
            "recovery_count_in_trend": 0,
            "trend_exit_candidate_count": 0,
            "trend_entry_candidate_count": 0,
            "trend_entry_price_history": [str(price)],
            "trend_entry_velocity_pct_per_tick": "0",
            "harvested_profit_usdt": "0",
            "averaging_spent_usdt": "0",
            "last_transfer_tick": -999999,
            "last_loss_reduce_tick": -999999,
            "last_transfer_price": None,
            "last_loss_reduce_price": None,
            "last_block_code": None,
            "tick_count": 0,
            "regime": "UNKNOWN",
            "regime_stable": "UNKNOWN",
            "regime_raw": "UNKNOWN",
            "regime_candidate": "",
            "regime_candidate_count": 0,
            "regime_price_history": [float(price)],
            "regime_features": {},
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

    def on_tick(self, state: dict[str, Any], price: Decimal) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        return self._on_price(state, price, closed_candle=True)

    def on_intrabar_price(
        self,
        state: dict[str, Any],
        price: Decimal,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Evaluate an observable intrabar price without advancing close-only indicators."""
        return self._on_price(state, price, closed_candle=False)

    def _on_price(
        self,
        state: dict[str, Any],
        price: Decimal,
        *,
        closed_candle: bool,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        state = deepcopy(state)
        if closed_candle:
            self.advance_close(state, price, resolve_lifecycle=False)
        else:
            state["last_price"] = str(price)
            state["high_since_base"] = str(max(d(state["high_since_base"]), price))
            state["low_since_base"] = str(min(d(state["low_since_base"]), price))
            self.mark_to_market(state, price)

        strategy_events: list[dict[str, Any]] = []
        risk_state = self.current_risk_state(state, price)
        risk_events: list[dict[str, Any]] = []

        if state.get("state") == "STOPPED":
            self.clear_blocked_decision(state)
            risk_events = self.risk_events_for_state(state, price, risk_state)
        elif risk_state.symbol_stopped:
            self.clear_blocked_decision(state)
            risk_events.append(self.execute_stop_unwind(state, price, risk_state))
        else:
            risk_events = self.risk_events_for_state(state, price, risk_state)
            event, blocked = self.apply_target_exposure_event(state, price)
            if event is not None:
                strategy_events.append(event)
            if blocked is not None:
                risk_events.append(blocked)

        state["state"] = self.lifecycle.resolve_state(state)
        state["updated_at"] = now_iso()
        self.mark_to_market(state, price)
        return state, strategy_events, risk_events

    def advance_close(
        self,
        state: dict[str, Any],
        price: Decimal,
        *,
        close_time: int | None = None,
        resolve_lifecycle: bool = True,
    ) -> dict[str, Any]:
        """Advance close-only indicators and lifecycle without deciding or trading."""
        state["tick_count"] = int(state.get("tick_count", 0)) + 1
        state["last_price"] = str(price)
        if close_time is not None:
            state["last_kline_close_time"] = int(close_time)
            state["last_kline_at"] = now_iso()
        state["high_since_base"] = str(max(d(state.get("high_since_base") or state["base_price"]), price))
        state["low_since_base"] = str(min(d(state.get("low_since_base") or state["base_price"]), price))
        self.regime_gate.update(state, float(price))
        self.mark_to_market(state, price)
        self.lifecycle.update_trend_tracking(state, price)
        if resolve_lifecycle:
            state["state"] = self.lifecycle.resolve_state(state)
        state["updated_at"] = now_iso()
        return state

    def execute_paper_tick(
        self,
        state: dict[str, Any],
        price: Decimal,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """paper 模式：行情推进已由 MarketFeedService 完成，本方法只做
        决策 → 规则 → guard → 虚拟成交（原地演进 state 的虚拟仓位与账本）。"""
        strategy_events: list[dict[str, Any]] = []
        risk_state = self.current_risk_state(state, price)
        if state.get("state") == "STOPPED":
            self.clear_blocked_decision(state)
            risk_events = self.risk_events_for_state(state, price, risk_state)
        elif risk_state.symbol_stopped:
            self.clear_blocked_decision(state)
            risk_events = [self.execute_stop_unwind(state, price, risk_state)]
        else:
            risk_events = self.risk_events_for_state(state, price, risk_state)
            event, blocked = self.apply_target_exposure_event(state, price)
            if event is not None:
                strategy_events.append(event)
            if blocked is not None:
                risk_events.append(blocked)
        state["state"] = self.lifecycle.resolve_state(state)
        state["updated_at"] = now_iso()
        self.mark_to_market(state, price)
        return strategy_events, risk_events

    def mark_to_market(self, state: dict[str, Any], price: Decimal) -> None:
        long_qty = d(state["long_qty"])
        short_qty = d(state["short_qty"])
        long_entry = d(state["long_entry_price"] or price)
        short_entry = d(state["short_entry_price"] or price)
        long_unrealized = (price - long_entry) * long_qty
        short_unrealized = (short_entry - price) * short_qty
        state["long_unrealized_pnl"] = str(q(long_unrealized))
        state["short_unrealized_pnl"] = str(q(short_unrealized))
        state["net_exposure"] = str(q((long_qty - short_qty) * price))
        state["gross_exposure"] = str(q((long_qty + short_qty) * price))
        equity = d(state["budget_usdt"]) + d(state["realized_pnl"]) + long_unrealized + short_unrealized
        state["equity"] = str(q(equity))

    def check_risk(self, state: dict[str, Any], price: Decimal) -> list[dict[str, Any]]:
        return self.risk_events_for_state(state, price, self.current_risk_state(state, price))

    def current_risk_state(self, state: dict[str, Any], price: Decimal) -> RiskState:
        return evaluate_risk(self.risk_context(state, price), self.risk_policy())

    def risk_context(self, state: dict[str, Any], price: Decimal) -> RiskContext:
        self.mark_to_market(state, price)
        return RiskContext(
            symbol=state["symbol"],
            price=price,
            long_qty=d(state["long_qty"]),
            short_qty=d(state["short_qty"]),
            budget_usdt=d(state["budget_usdt"]),
            realized_pnl=d(state["realized_pnl"]),
            long_unrealized_pnl=d(state["long_unrealized_pnl"]),
            short_unrealized_pnl=d(state["short_unrealized_pnl"]),
            harvested_profit_usdt=d(state.get("harvested_profit_usdt") or 0),
            averaging_spent_usdt=d(state.get("averaging_spent_usdt") or 0),
        )

    def risk_policy(self) -> RiskPolicy:
        return RiskPolicy.from_config(self.config)

    def risk_events_for_state(self, state: dict[str, Any], price: Decimal, risk_state: RiskState) -> list[dict[str, Any]]:
        guard_result = guard_actions([], self.risk_context(state, price), self.risk_policy())
        events: list[dict[str, Any]] = []
        if risk_state.gross_exceeded:
            events.append({
                "id": self.uid("risk"),
                "timestamp": now_iso(),
                "symbol": state["symbol"],
                "risk_level": "high",
                "risk_type": "MAX_GROSS_EXPOSURE",
                "action_taken": "ONLY_REDUCE",
                "message": "总敞口超过单币种上限，已进入 ONLY_REDUCE。",
                "risk_checks": guard_result.checks,
            })

        if risk_state.symbol_stopped:
            events.append({
                "id": self.uid("risk"),
                "timestamp": now_iso(),
                "symbol": state["symbol"],
                "risk_level": "high",
                "risk_type": "MAX_SYMBOL_DRAWDOWN",
                "action_taken": "STOPPED",
                "message": "单币种回撤超过上限，进入 STOPPED 吸收态。",
                "risk_checks": guard_result.checks,
            })
        return events

    def execute_stop_unwind(self, state: dict[str, Any], price: Decimal, risk_state: RiskState) -> dict[str, Any]:
        state_before = state.get("state", "BALANCED")
        candidates: list[dict[str, Any]] = []
        if d(state["long_qty"]) > 0:
            candidates.append(self.trade_candidate(
                "REDUCE_LONG", d(state["long_qty"]), price,
                "symbol_drawdown_stop_unwind_long",
                risk_intent="STOP_UNWIND",
            ))
        if d(state["short_qty"]) > 0:
            candidates.append(self.trade_candidate(
                "REDUCE_SHORT", d(state["short_qty"]), price,
                "symbol_drawdown_stop_unwind_short",
                risk_intent="STOP_UNWIND",
            ))

        guard_result = self.guard_trade_actions(state, price, candidates)
        trades = [
            self.apply_trade(state, price, item["action"], d(item["quantity"]), "STOP_UNWIND", item["reason"])
            for item in guard_result.planned_actions
        ]
        state["state"] = "STOPPED"

        return {
            "id": self.uid("risk"),
            "timestamp": now_iso(),
            "symbol": state["symbol"],
            "risk_level": "critical",
            "risk_type": "MAX_SYMBOL_DRAWDOWN",
            "action_taken": "STOPPED_UNWIND",
            "state_before": state_before,
            "state_after": state["state"],
            "message": "单币种回撤超过上限，执行拆对冲全平并进入 STOPPED。",
            "risk_checks": guard_result.checks,
            "trigger": {
                "total_pnl_usdt": f(risk_state.total_pnl_usdt),
                "drawdown_limit_usdt": f(risk_state.drawdown_limit_usdt),
            },
            "status": "filled" if trades else "blocked",
            "trades": trades,
        }

    def guard_trade_actions(
        self,
        state: dict[str, Any],
        price: Decimal,
        actions: list[dict[str, Any]],
    ) -> RiskGuardResult:
        return guard_actions(actions, self.risk_context(state, price), self.risk_policy())

    def trade_candidate(
        self,
        action: str,
        qty: Decimal,
        price: Decimal,
        reason: str,
        *,
        risk_intent: str = "STRATEGY",
        event_role: str | None = None,
    ) -> dict[str, Any]:
        qty = q(max(Decimal("0"), qty), QTY_STEP)
        return {
            "action": action,
            "quantity": f(qty),
            "notional_usdt": f(q(qty * price)),
            "status": "planned",
            "risk_intent": risk_intent,
            "event_role": event_role or action,
            "reason": reason,
        }

    def trade_candidate_from_strategy_action(self, action: StrategyAction, price: Decimal) -> dict[str, Any]:
        return self.trade_candidate(
            action.action,
            action.quantity,
            price,
            action.reason,
            risk_intent=action.risk_intent,
            event_role=action.event_role,
        )

    def strategy_position(self, state: dict[str, Any], price: Decimal) -> StrategyPosition:
        return StrategyPosition(
            symbol=state["symbol"],
            price=price,
            budget_usdt=d(state["budget_usdt"]),
            base_position_usdt=self.base_position_usdt,
            long=StrategyLeg(
                side="LONG",
                qty=d(state["long_qty"]),
                entry_price=d(state["long_entry_price"] or price),
                mark_price=price,
                unrealized_pnl=d(state["long_unrealized_pnl"]),
                notional=abs(d(state["long_qty"]) * price),
            ),
            short=StrategyLeg(
                side="SHORT",
                qty=d(state["short_qty"]),
                entry_price=d(state["short_entry_price"] or price),
                mark_price=price,
                unrealized_pnl=d(state["short_unrealized_pnl"]),
                notional=abs(d(state["short_qty"]) * price),
            ),
        )

    def strategy_action_set(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
    ) -> StrategyActionSet | None:
        return build_strategy_action_set(decision, self.strategy_position(state, price), self.config)

    def execute_action_set(
        self,
        state: dict[str, Any],
        price: Decimal,
        action_set: StrategyActionSet,
    ) -> tuple[list[dict[str, Any]], RiskGuardResult]:
        guard_result = self.guard_trade_actions(
            state,
            price,
            [self.trade_candidate_from_strategy_action(action, price) for action in action_set.actions],
        )
        trades = [
            self.apply_trade(
                state,
                price,
                item["action"],
                d(item["quantity"]),
                item.get("event_role", item["action"]),
                item["reason"],
            )
            for item in guard_result.planned_actions
        ]
        return trades, guard_result

    def planned_quantity_by_role(self, guard_result: RiskGuardResult, event_role: str) -> Decimal:
        return sum(d(item["quantity"]) for item in guard_result.planned_actions if item.get("event_role") == event_role)

    def execute_strategy_event(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
        action_set: StrategyActionSet,
        rule_result: EventRuleResult,
    ) -> dict[str, Any] | None:
        state_before = state["state"]
        trades, guard_result = self.execute_action_set(state, price, action_set)
        if not trades:
            return None

        self.lifecycle.apply_event(state, price, decision, action_set)

        return self.strategy_event(
            event_type=action_set.event_type,
            state_before=state_before,
            state_after=state["state"],
            symbol=state["symbol"],
            direction=action_set.direction,
            reason=action_set.reason,
            trades=trades,
            trigger={
                **decision.context(),
                "price": f(price),
                "event_rule": rule_result.code,
                **rule_result.context,
                **action_set.trigger,
            },
            sizing={**action_set.sizing, **self.actual_sizing_by_event(action_set.event_type, guard_result)},
            risk_checks=guard_result.checks,
            blocked_actions=guard_result.blocked_actions,
        )

    def actual_sizing_by_event(self, event_type: str, guard_result: RiskGuardResult) -> dict[str, str]:
        if event_type.startswith("PROFIT_TRANSFER"):
            return {
                "actual_reduce_qty": f(self.planned_quantity_by_role(guard_result, "REDUCE_PROFIT_SIDE")),
                "actual_add_qty": f(self.planned_quantity_by_role(guard_result, "ADD_LOSS_SIDE")),
            }
        if event_type.startswith("LOSS_SIDE_REDUCTION"):
            return {
                "actual_reduce_qty": f(self.planned_quantity_by_role(guard_result, "LOSS_SIDE_REDUCTION")),
            }
        if event_type.startswith("POSITION_RECOVERY"):
            return {
                "actual_reduce_qty": f(self.planned_quantity_by_role(guard_result, "POSITION_RECOVERY")),
            }
        if event_type.startswith("POSITION_REBUILD"):
            return {
                "actual_add_qty": f(self.planned_quantity_by_role(guard_result, "POSITION_REBUILD")),
            }
        return {}

    def apply_target_exposure_event(
        self,
        state: dict[str, Any],
        price: Decimal,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        decision = decide_target_exposure(
            price=price,
            base_price=d(state["base_price"]),
            base_qty=d(state["base_qty"]),
            long_qty=d(state["long_qty"]),
            short_qty=d(state["short_qty"]),
            strategy=self.config,
        )
        if not decision.has_action:
            self.clear_blocked_decision(state)
            return None, None

        rule_result = self.event_rules.evaluate(decision, state, price)
        regime_result = self.regime_gate.evaluate(decision, state)
        if not regime_result.allowed:
            return None, self.blocked_decision_event(state, price, decision, regime_result, "regime_gate")
        if not rule_result.allowed:
            return None, self.blocked_decision_event(state, price, decision, rule_result, "event_rule")

        self.clear_blocked_decision(state)
        action_set = self.strategy_action_set(state, price, decision)
        if action_set is None:
            return None, None

        return self.execute_strategy_event(state, price, decision, action_set, rule_result), None

    def blocked_decision_event(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
        result: EventRuleResult | RegimeGateResult,
        source: str,
    ) -> dict[str, Any] | None:
        if state.get("last_block_code") == result.code:
            return None
        state["last_block_code"] = result.code
        trigger = {
            **decision.context(),
            "price": f(price),
            "block_source": source,
            "block_code": result.code,
            **result.context,
        }
        return {
            "id": self.uid("risk"),
            "timestamp": now_iso(),
            "symbol": state["symbol"],
            "risk_level": "info",
            "risk_type": result.code,
            "action_taken": "BLOCKED_NO_TRADE",
            "message": result.reason,
            "status": "blocked",
            "trigger": trigger,
            "context": trigger,
            "risk_checks": [{
                "name": result.code,
                "ok": False,
                "message": result.reason,
                **result.context,
            }],
            "trades": [],
        }

    def clear_blocked_decision(self, state: dict[str, Any]) -> None:
        state["last_block_code"] = None

    def apply_trade(self, state: dict[str, Any], price: Decimal, action: str, qty: Decimal, event_type: str, reason: str) -> dict[str, Any]:
        qty = q(qty, QTY_STEP)
        fill = self.fill_price(price, action)
        notional = q(fill * qty)
        fee = q(notional * d(self.costs["taker_fee_rate"]))
        slippage_cost = q(abs(fill - price) * qty)
        realized = Decimal("0")
        side = "BUY" if action in ("ADD_LONG", "REDUCE_SHORT") else "SELL"
        position_side = "LONG" if action.endswith("LONG") else "SHORT"

        if action == "ADD_LONG":
            old_qty = d(state["long_qty"])
            old_entry = d(state["long_entry_price"] or fill)
            new_qty = old_qty + qty
            state["long_entry_price"] = str(q((old_qty * old_entry + qty * fill) / new_qty, Decimal("0.000000000001")))
            state["long_qty"] = str(q(new_qty, QTY_STEP))
            realized -= fee
        elif action == "ADD_SHORT":
            old_qty = d(state["short_qty"])
            old_entry = d(state["short_entry_price"] or fill)
            new_qty = old_qty + qty
            state["short_entry_price"] = str(q((old_qty * old_entry + qty * fill) / new_qty, Decimal("0.000000000001")))
            state["short_qty"] = str(q(new_qty, QTY_STEP))
            realized -= fee
        elif action == "REDUCE_LONG":
            qty = min(qty, d(state["long_qty"]))
            fill = self.fill_price(price, action)
            notional = q(fill * qty)
            fee = q(notional * d(self.costs["taker_fee_rate"]))
            slippage_cost = q(abs(fill - price) * qty)
            realized = q((fill - d(state["long_entry_price"])) * qty - fee)
            state["long_qty"] = str(q(d(state["long_qty"]) - qty, QTY_STEP))
        elif action == "REDUCE_SHORT":
            qty = min(qty, d(state["short_qty"]))
            fill = self.fill_price(price, action)
            notional = q(fill * qty)
            fee = q(notional * d(self.costs["taker_fee_rate"]))
            slippage_cost = q(abs(fill - price) * qty)
            realized = q((d(state["short_entry_price"]) - fill) * qty - fee)
            state["short_qty"] = str(q(d(state["short_qty"]) - qty, QTY_STEP))
        else:
            raise ValueError(f"Unsupported action: {action}")

        state["realized_pnl"] = str(q(d(state["realized_pnl"]) + realized))
        state["fee_total"] = str(q(d(state["fee_total"]) + fee))
        state["slippage_total"] = str(q(d(state["slippage_total"]) + slippage_cost))
        # C7 自融资账本：收割 = 减仓的正已实现收益；花费 = 加亏损腿名义
        if action.startswith("REDUCE_") and realized > Decimal("0"):
            state["harvested_profit_usdt"] = str(q(d(state.get("harvested_profit_usdt") or 0) + realized))
        if event_type == "ADD_LOSS_SIDE":
            state["averaging_spent_usdt"] = str(q(d(state.get("averaging_spent_usdt") or 0) + notional))
        self.mark_to_market(state, price)

        return {
            "id": self.uid("trade"),
            "timestamp": now_iso(),
            "symbol": state["symbol"],
            "event_type": event_type,
            "side": side,
            "position_side": position_side,
            "action": action,
            "price": f(price),
            "fill_price": f(fill),
            "qty": f(qty),
            "notional": f(notional),
            "fee": f(fee),
            "slippage_cost": f(slippage_cost),
            "funding_fee": 0.0,
            "realized_pnl": f(realized),
            "reason": reason,
            "status": "filled",
        }

    def fill_price(self, price: Decimal, action: str) -> Decimal:
        slip = pct(d(self.costs["slippage_bps"]) / Decimal("100"))
        if action in ("ADD_LONG", "REDUCE_SHORT"):
            return q(price * (Decimal("1") + slip), Decimal("0.000000000001"))
        return q(price * (Decimal("1") - slip), Decimal("0.000000000001"))

    def strategy_event(
        self,
        event_type: str,
        state_before: str,
        state_after: str,
        symbol: str,
        direction: str,
        reason: str,
        trades: list[dict[str, Any]],
        trigger: dict[str, Any] | None = None,
        sizing: dict[str, Any] | None = None,
        risk_checks: list[dict[str, Any]] | None = None,
        blocked_actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": self.uid("event"),
            "timestamp": now_iso(),
            "symbol": symbol,
            "event_type": event_type,
            "direction": direction,
            "state_before": state_before,
            "state_after": state_after,
            "reason": reason,
            "trigger": trigger or {},
            "sizing": sizing or {},
            "risk_checks": risk_checks or [],
            "blocked_actions": blocked_actions or [],
            "realized_pnl": f(sum(d(t["realized_pnl"]) for t in trades)),
            "fee_total": f(sum(d(t["fee"]) for t in trades)),
            "slippage_total": f(sum(d(t["slippage_cost"]) for t in trades)),
            "status": "filled",
            "trades": trades,
        }

    def uid(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:16]}"
