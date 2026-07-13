from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from orbit.domain.strategy.exposure import TargetExposureDecision, strategy_body


ZERO = Decimal("0")
HUNDRED = Decimal("100")


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def pct(value: Any) -> Decimal:
    return dec(value) / HUNDRED


@dataclass(frozen=True)
class EventRuleResult:
    allowed: bool
    code: str
    reason: str
    context: dict[str, str]

    @classmethod
    def allow(cls, code: str = "ALLOWED", **context: Any) -> "EventRuleResult":
        return cls(True, code, "event rule allowed", stringify_context(context))

    @classmethod
    def block(cls, code: str, reason: str, **context: Any) -> "EventRuleResult":
        return cls(False, code, reason, stringify_context(context))


class StrategyEventRules:
    def __init__(self, strategy_config: dict[str, Any]):
        self.body = strategy_body(strategy_config)
        self.events = self.body["events"]

    def evaluate(
        self,
        decision: TargetExposureDecision,
        state: dict[str, Any],
        price: Decimal,
    ) -> EventRuleResult:
        event_type = str(decision.event_type or "")
        if event_type.startswith("PROFIT_TRANSFER"):
            return self.profit_transfer_rule(decision, state, price)
        if event_type.startswith("LOSS_SIDE_REDUCTION"):
            return self.loss_side_reduction_rule(decision, state, price)
        if event_type.startswith("POSITION_RECOVERY") or event_type.startswith("POSITION_REBUILD"):
            return self.position_recovery_rule(state, price)
        return EventRuleResult.block("UNKNOWN_EVENT_TYPE", "unsupported strategy event", event_type=event_type)

    def profit_transfer_rule(
        self,
        decision: TargetExposureDecision,
        state: dict[str, Any],
        price: Decimal,
    ) -> EventRuleResult:
        cfg = self.events["profit_transfer"]
        if not cfg.get("enabled", True):
            return EventRuleResult.block("EVENT_DISABLED", "profit transfer is disabled")

        guard = cfg.get("guard", {})
        if guard.get("skip_if_trend_confirmed", True) and str(state.get("state") or "").startswith("TREND_"):
            return EventRuleResult.block(
                "TREND_CONFIRMED",
                "profit transfer is disabled while trend is confirmed",
                price=price,
                state=state.get("state"),
            )

        extended = dec(guard.get("skip_if_price_extended_pct_from_base"))
        if extended > ZERO and abs(decision.move_pct) >= extended:
            return EventRuleResult.block(
                "PRICE_EXTENDED",
                "profit transfer is disabled beyond extension guard",
                move_pct=decision.move_pct,
                skip_if_price_extended_pct_from_base=extended,
            )

        count = int(state.get("profit_transfer_count_in_trend", 0))
        max_times = int(guard["max_times_per_trend"])
        if count >= max_times:
            return EventRuleResult.block(
                "MAX_TIMES_PER_TREND",
                "profit transfer reached max_times_per_trend",
                current_count=count,
                max_times=max_times,
            )

        tick_count = int(state.get("tick_count", 0))
        last_tick = int(state.get("last_transfer_tick", -999999))
        cooldown = int(guard.get("cooldown_ticks", 0))
        if tick_count - last_tick < cooldown:
            return EventRuleResult.block(
                "COOLDOWN_ACTIVE",
                "profit transfer cooldown is active",
                tick_count=tick_count,
                last_tick=last_tick,
                cooldown_ticks=cooldown,
            )

        return EventRuleResult.allow("PROFIT_TRANSFER_ALLOWED", current_count=count)

    def loss_side_reduction_rule(
        self,
        decision: TargetExposureDecision,
        state: dict[str, Any],
        price: Decimal,
    ) -> EventRuleResult:
        cfg = self.events["loss_side_reduction"]
        if not cfg.get("enabled", True):
            return EventRuleResult.block("EVENT_DISABLED", "loss side reduction is disabled")

        # 趋势进入持续确认：未在趋势态时，需连续 N tick 满足 |m|≥θ_t 才允许进入
        current_state = str(state.get("state") or "")
        if not current_state.startswith("TREND_"):
            required_ticks = max(1, int(cfg.get("guard", {}).get("trend_entry_confirm_ticks", 1)))
            entry_count = int(state.get("trend_entry_candidate_count", 0))
            if entry_count < required_ticks:
                return EventRuleResult.block(
                    "TREND_ENTRY_NOT_CONFIRMED",
                    "trend entry needs consecutive confirming ticks",
                    trend_entry_candidate_count=entry_count,
                    trend_entry_confirm_ticks=required_ticks,
                    trend_entry_velocity_pct_per_tick=state.get("trend_entry_velocity_pct_per_tick", 0),
                    trend_entry_min_velocity_pct_per_tick=cfg.get("trigger", {}).get(
                        "trend_entry_min_velocity_pct_per_tick", 0,
                    ),
                )

        tick_count = int(state.get("tick_count", 0))
        last_tick = int(state.get("last_loss_reduce_tick", -999999))
        cooldown = int(cfg["guard"].get("cooldown_ticks", 0))
        if tick_count - last_tick < cooldown:
            return EventRuleResult.block(
                "COOLDOWN_ACTIVE",
                "loss side reduction cooldown is active",
                tick_count=tick_count,
                last_tick=last_tick,
                cooldown_ticks=cooldown,
            )

        step = dec(cfg["trigger"]["reduce_step_pct"])
        base = dec(state["base_price"])
        trigger = dec(cfg["trigger"]["trend_confirm_move_pct_from_base"])
        if decision.delta_qty > ZERO:
            last_price = dec(state.get("last_loss_reduce_price") or base * (Decimal("1") + pct(trigger - step)))
            required_price = last_price * (Decimal("1") + pct(step))
            if price < required_price:
                return EventRuleResult.block(
                    "TREND_STEP_NOT_REACHED",
                    "uptrend loss side reduction step is not reached",
                    price=price,
                    last_price=last_price,
                    required_price=required_price,
                )
        else:
            last_price = dec(state.get("last_loss_reduce_price") or base * (Decimal("1") - pct(trigger - step)))
            required_price = last_price * (Decimal("1") - pct(step))
            if price > required_price:
                return EventRuleResult.block(
                    "TREND_STEP_NOT_REACHED",
                    "downtrend loss side reduction step is not reached",
                    price=price,
                    last_price=last_price,
                    required_price=required_price,
                )

        return EventRuleResult.allow("LOSS_SIDE_REDUCTION_ALLOWED")

    def position_recovery_rule(self, state: dict[str, Any], price: Decimal) -> EventRuleResult:
        cfg = self.events["position_recovery"]
        if not cfg.get("enabled", True):
            return EventRuleResult.block("EVENT_DISABLED", "position recovery is disabled")
        current = str(state.get("state") or "")
        if current.startswith("TREND_"):
            required = int(cfg["trigger"].get("trend_exit_confirm_ticks", 1))
            current_count = int(state.get("trend_exit_candidate_count", 0))
            if current_count < required:
                return EventRuleResult.block(
                    "TREND_EXIT_NOT_CONFIRMED",
                    "trend exit requires pullback, return band, and sustained confirmation",
                    price=price,
                    trend_exit_candidate_count=current_count,
                    trend_exit_confirm_ticks=required,
                )
        return EventRuleResult.allow("POSITION_RECOVERY_ALLOWED")


def stringify_context(context: dict[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in context.items()}
