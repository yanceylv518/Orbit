from __future__ import annotations

from decimal import Decimal
from typing import Any

from orbit.domain.strategy.actions import StrategyActionSet
from orbit.domain.strategy.exposure import TargetExposureDecision, q, strategy_body


ZERO = Decimal("0")


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


class StrategyLifecycle:
    def __init__(self, strategy_config: dict[str, Any]):
        self.body = strategy_body(strategy_config)
        self.events = self.body["events"]

    def apply_event(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
        action_set: StrategyActionSet,
    ) -> None:
        event_type = action_set.event_type
        if event_type.startswith("PROFIT_TRANSFER"):
            self.apply_profit_transfer(state, price, decision)
            return

        if event_type.startswith("LOSS_SIDE_REDUCTION"):
            self.apply_loss_side_reduction(state, price, decision)
            return

        if event_type.startswith("POSITION_RECOVERY") or event_type.startswith("POSITION_REBUILD"):
            self.apply_position_recovery(state, price, decision)

    def update_trend_tracking(self, state: dict[str, Any], price: Decimal) -> None:
        self.update_trend_entry_history(state, price)
        current = str(state.get("state") or "")
        if current == "TREND_UP":
            state["trend_extreme_price"] = str(max(
                dec(state.get("trend_extreme_price") or price),
                dec(state.get("high_since_base") or price),
                price,
            ))
        elif current == "TREND_DOWN":
            state["trend_extreme_price"] = str(min(
                dec(state.get("trend_extreme_price") or price),
                dec(state.get("low_since_base") or price),
                price,
            ))
        else:
            state["trend_exit_candidate_count"] = 0
            # 趋势进入持续确认：未在趋势态时，统计连续满足 |m|≥θ_t 的 tick 数
            if self.is_trend_entry_candidate(state, price):
                state["trend_entry_candidate_count"] = int(state.get("trend_entry_candidate_count", 0)) + 1
            else:
                state["trend_entry_candidate_count"] = 0
            return

        state["trend_entry_candidate_count"] = 0
        if self.is_trend_exit_candidate(state, price):
            state["trend_exit_candidate_count"] = int(state.get("trend_exit_candidate_count", 0)) + 1
        else:
            state["trend_exit_candidate_count"] = 0

    def is_trend_entry_candidate(self, state: dict[str, Any], price: Decimal) -> bool:
        base_price = dec(state.get("base_price"))
        if base_price <= ZERO or price <= ZERO:
            return False
        trigger = self.events["loss_side_reduction"]["trigger"]
        theta_t = dec(trigger["trend_confirm_move_pct_from_base"])
        move_abs = abs((price / base_price - Decimal("1")) * Decimal("100"))
        if theta_t <= ZERO or move_abs < theta_t:
            return False

        minimum_velocity = dec(trigger.get("trend_entry_min_velocity_pct_per_tick"))
        if minimum_velocity <= ZERO:
            return True
        velocity = dec(state.get("trend_entry_velocity_pct_per_tick"))
        history = state.get("trend_entry_price_history") or []
        window = self.trend_entry_velocity_window_ticks()
        return len(history) >= window + 1 and velocity >= minimum_velocity

    def update_trend_entry_history(self, state: dict[str, Any], price: Decimal) -> None:
        window = self.trend_entry_velocity_window_ticks()
        history = [dec(item) for item in state.get("trend_entry_price_history", []) if dec(item) > ZERO]
        history.append(price)
        history = history[-(window + 1):]
        state["trend_entry_price_history"] = [str(item) for item in history]
        if len(history) < window + 1 or history[0] <= ZERO:
            state["trend_entry_velocity_pct_per_tick"] = "0"
            return
        velocity = abs((price / history[0] - Decimal("1")) * Decimal("100")) / Decimal(window)
        state["trend_entry_velocity_pct_per_tick"] = str(velocity)

    def trend_entry_velocity_window_ticks(self) -> int:
        trigger = self.events["loss_side_reduction"]["trigger"]
        return max(1, int(trigger.get("trend_entry_velocity_window_ticks", 3)))

    def trend_entry_confirm_ticks(self) -> int:
        guard = self.events["loss_side_reduction"].get("guard", {})
        return max(1, int(guard.get("trend_entry_confirm_ticks", 1)))

    def is_trend_exit_candidate(self, state: dict[str, Any], price: Decimal) -> bool:
        direction = self.trend_direction(state)
        if direction == 0:
            return False

        base_price = dec(state.get("base_price"))
        extreme_price = dec(state.get("trend_extreme_price") or price)
        if base_price <= ZERO or extreme_price <= ZERO or price <= ZERO:
            return False

        loss_cfg = self.events["loss_side_reduction"]
        recovery_cfg = self.events["position_recovery"]
        theta_t = dec(loss_cfg["trigger"]["trend_confirm_move_pct_from_base"])
        theta_out = dec(recovery_cfg["trigger"].get(
            "trend_exit_move_pct_from_base",
            theta_t * Decimal("0.7"),
        ))
        pullback_required = dec(recovery_cfg["trigger"].get("pullback_pct_from_trend_extreme"))
        move_abs = abs((price / base_price - Decimal("1")) * Decimal("100"))

        if direction > 0:
            pullback = (extreme_price / price - Decimal("1")) * Decimal("100")
        else:
            pullback = (price / extreme_price - Decimal("1")) * Decimal("100")

        return pullback >= pullback_required and move_abs <= theta_out

    def trend_direction(self, state: dict[str, Any]) -> int:
        current = str(state.get("state") or "")
        if current == "TREND_UP":
            return 1
        if current == "TREND_DOWN":
            return -1
        return 0

    def apply_profit_transfer(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
    ) -> None:
        state["profit_transfer_count_in_trend"] = int(state.get("profit_transfer_count_in_trend", 0)) + 1
        state["last_transfer_tick"] = state["tick_count"]
        state["last_transfer_price"] = str(price)
        state["trend_extreme_price"] = str(price)
        state["state"] = decision.lifecycle_state

    def apply_loss_side_reduction(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
    ) -> None:
        state["loss_side_reduce_count_in_trend"] = int(state.get("loss_side_reduce_count_in_trend", 0)) + 1
        state["last_loss_reduce_tick"] = state["tick_count"]
        state["last_loss_reduce_price"] = str(price)
        state["trend_extreme_price"] = str(price)
        state["trend_exit_candidate_count"] = 0
        state["state"] = decision.lifecycle_state

    def apply_position_recovery(
        self,
        state: dict[str, Any],
        price: Decimal,
        decision: TargetExposureDecision,
    ) -> None:
        state["recovery_count_in_trend"] = int(state.get("recovery_count_in_trend", 0)) + 1
        state["state"] = decision.lifecycle_state
        if self.should_reanchor_after_recovery(state):
            self.reanchor(state, price)

    def should_reanchor_after_recovery(self, state: dict[str, Any]) -> bool:
        return self.is_net_balanced(state) and self.are_legs_rebuilt(state)

    def is_net_balanced(self, state: dict[str, Any]) -> bool:
        cfg = self.events["position_recovery"]
        base_qty = dec(state.get("base_qty"))
        if base_qty <= ZERO:
            return False
        target = dec(cfg["target"]["target_balance_position_distance_pct"])
        return abs(dec(state.get("long_qty")) - dec(state.get("short_qty"))) <= base_qty * target

    def are_legs_rebuilt(self, state: dict[str, Any]) -> bool:
        cfg = self.events["position_recovery"]
        base_qty = dec(state.get("base_qty"))
        if base_qty <= ZERO:
            return False
        target = dec(cfg["target"]["target_balance_position_distance_pct"])
        min_qty = base_qty * (Decimal("1") - target)
        return dec(state.get("long_qty")) >= min_qty and dec(state.get("short_qty")) >= min_qty

    def reanchor(self, state: dict[str, Any], price: Decimal) -> None:
        base_position_usdt = dec(self.body.get("base_position_usdt"))
        if base_position_usdt > ZERO and price > ZERO:
            state["base_qty"] = str(q(base_position_usdt / price))
        state["base_price"] = str(price)
        state["high_since_base"] = str(price)
        state["low_since_base"] = str(price)
        state["trend_extreme_price"] = str(price)
        state["profit_transfer_count_in_trend"] = 0
        state["loss_side_reduce_count_in_trend"] = 0
        state["recovery_count_in_trend"] = 0
        state["trend_exit_candidate_count"] = 0
        state["trend_entry_candidate_count"] = 0
        state["trend_entry_price_history"] = [str(price)]
        state["trend_entry_velocity_pct_per_tick"] = "0"
        state["last_transfer_tick"] = -999999
        state["last_loss_reduce_tick"] = -999999
        state["last_transfer_price"] = None
        state["last_loss_reduce_price"] = None
        state["state"] = "BALANCED"

    def resolve_state(self, state: dict[str, Any]) -> str:
        current = state.get("state") or "BALANCED"
        base_qty = dec(state.get("base_qty"))
        if base_qty <= ZERO:
            return current

        if self.is_net_balanced(state) and self.are_legs_rebuilt(state) and current in {"BALANCE", "BALANCED", "REANCHORING"}:
            return "BALANCED"
        return current
