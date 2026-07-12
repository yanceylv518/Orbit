from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any


QTY_STEP = Decimal("0.00000001")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def pct(value: Any) -> Decimal:
    return dec(value) / HUNDRED


def q(value: Decimal, step: Decimal = QTY_STEP) -> Decimal:
    return value.quantize(step, rounding=ROUND_DOWN)


def sign(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def strategy_body(strategy: dict[str, Any]) -> dict[str, Any]:
    return strategy.get("strategy", strategy)


def derive_anchor_price(long_entry: Decimal, short_entry: Decimal, fallback: Decimal) -> Decimal:
    prices = [price for price in (long_entry, short_entry) if price > 0]
    if not prices:
        return fallback
    return sum(prices, ZERO) / Decimal(len(prices))


def net_quantity(long_qty: Decimal, short_qty: Decimal) -> Decimal:
    return long_qty - short_qty


def gross_quantity(long_qty: Decimal, short_qty: Decimal) -> Decimal:
    return long_qty + short_qty


def movement_pct(price: Decimal, base_price: Decimal) -> Decimal:
    if base_price <= 0:
        return ZERO
    return (price / base_price - ONE) * HUNDRED


@dataclass(frozen=True)
class TargetExposureDecision:
    event_type: str | None
    direction: str
    lifecycle_state: str
    reason: str
    price: Decimal
    base_price: Decimal
    move_pct: Decimal
    current_net_qty: Decimal
    target_net_qty: Decimal
    delta_qty: Decimal
    base_qty: Decimal
    step_count: int
    target_long_qty: Decimal | None = None
    target_short_qty: Decimal | None = None

    @property
    def has_action(self) -> bool:
        return self.event_type is not None and (
            q(abs(self.delta_qty)) > ZERO
            or self.target_long_qty is not None
            or self.target_short_qty is not None
        )

    def context(self) -> dict[str, float | int | str]:
        context: dict[str, float | int | str] = {
            "exposure_model": "net_exposure_v1",
            "lifecycle_state": self.lifecycle_state,
            "base_price": float(self.base_price),
            "move_pct_from_base": float(self.move_pct),
            "base_qty": float(self.base_qty),
            "current_net_qty": float(self.current_net_qty),
            "target_net_qty": float(self.target_net_qty),
            "delta_to_target_qty": float(self.delta_qty),
            "target_step_count": self.step_count,
            "target_reason": self.reason,
        }
        if self.target_long_qty is not None:
            context["target_long_qty"] = float(self.target_long_qty)
        if self.target_short_qty is not None:
            context["target_short_qty"] = float(self.target_short_qty)
        return context


def decide_target_exposure(
    *,
    price: Decimal,
    base_price: Decimal,
    base_qty: Decimal,
    long_qty: Decimal,
    short_qty: Decimal,
    strategy: dict[str, Any],
) -> TargetExposureDecision:
    body = strategy_body(strategy)
    events = body["events"]
    profit_cfg = events["profit_transfer"]
    loss_cfg = events["loss_side_reduction"]
    recovery_cfg = events["position_recovery"]

    current_net = q(net_quantity(long_qty, short_qty))
    move = movement_pct(price, base_price)
    move_abs = abs(move)
    move_sign = sign(move)
    current_sign = sign(current_net)

    a_pt = dec(profit_cfg["trigger"]["min_price_move_pct_from_base"])
    theta_t = dec(loss_cfg["trigger"]["trend_confirm_move_pct_from_base"])
    max_steps = max(1, int(profit_cfg["guard"].get("max_times_per_trend", 1)))
    skew_unit = q(base_qty * dec(profit_cfg["sizing"]["reduce_profit_side_ratio"]))
    q_floor = q(base_qty * dec(loss_cfg["sizing"]["min_loss_side_position_ratio_of_base"]))
    target_distance = dec(recovery_cfg["target"]["target_balance_position_distance_pct"])
    target_price_distance = dec(recovery_cfg["target"].get("target_price_distance_pct_from_base", a_pt))
    rebuild_threshold = dec(recovery_cfg["trigger"].get(
        "min_position_distance_pct_from_base",
        target_distance,
    ))

    event_type: str | None = None
    direction = "-"
    lifecycle_state = "BALANCED"
    reason = "价格仍在锚点触发带内，目标净敞口为 0。"
    target_net = ZERO
    step_count = 0
    target_long_qty: Decimal | None = None
    target_short_qty: Decimal | None = None

    if move_sign and move_abs >= theta_t:
        target_net = q(Decimal(move_sign) * max(ZERO, base_qty - q_floor))
        direction = "UP" if move_sign > 0 else "DOWN"
        event_type = f"LOSS_SIDE_REDUCTION_{direction}"
        lifecycle_state = f"TREND_{direction}"
        reason = "价格进入趋势带，目标净敞口翻向趋势方向并砍亏损腿至地板。"
    elif move_sign and move_abs >= a_pt:
        raw_steps = int((move_abs / a_pt).to_integral_value(rounding=ROUND_DOWN))
        step_count = max(1, min(raw_steps, max_steps))
        target_net = q(Decimal(-move_sign) * skew_unit * Decimal(step_count))
        direction = "UP" if move_sign > 0 else "DOWN"
        event_type = f"PROFIT_TRANSFER_{direction}"
        lifecycle_state = "SKEWED_SHORT" if move_sign > 0 else "SKEWED_LONG"
        reason = "价格处于区间带，目标净敞口建立逆势偏斜，押注回归。"
    elif base_qty > 0 and abs(current_net) > base_qty * target_distance:
        target_net = ZERO
        direction = "UP" if current_sign < 0 else "DOWN"
        event_type = f"POSITION_RECOVERY_{direction}"
        lifecycle_state = "REANCHORING"
        reason = "价格回到触发带内，目标净敞口回到 0，平掉偏斜。"

    if event_type is None and base_qty > 0 and move_abs <= target_price_distance:
        long_deficit = q(max(ZERO, base_qty - long_qty))
        short_deficit = q(max(ZERO, base_qty - short_qty))
        if max(long_deficit, short_deficit) > base_qty * rebuild_threshold:
            target_net = current_net
            direction = "REBUILD"
            event_type = "POSITION_REBUILD"
            lifecycle_state = "REANCHORING"
            target_long_qty = q(base_qty)
            target_short_qty = q(base_qty)
            reason = "price returned to reanchor band; rebuild both legs toward base position"

    delta = q(target_net - current_net)
    if event_type is not None and delta == ZERO and event_type != "POSITION_REBUILD":
        event_type = None
        direction = "-"
        reason = "当前净敞口已经处在目标净敞口附近。"

    return TargetExposureDecision(
        event_type=event_type,
        direction=direction,
        lifecycle_state=lifecycle_state,
        reason=reason,
        price=price,
        base_price=base_price,
        move_pct=move,
        current_net_qty=current_net,
        target_net_qty=target_net,
        delta_qty=delta,
        base_qty=q(base_qty),
        step_count=step_count,
        target_long_qty=target_long_qty,
        target_short_qty=target_short_qty,
    )
