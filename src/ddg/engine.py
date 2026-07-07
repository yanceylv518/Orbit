from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any
from uuid import uuid4


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
        self.base_position_usdt = d(strategy_config["strategy"]["base_position_usdt"])

    def initialize_symbol(self, symbol: str, price: Decimal, budget_usdt: Decimal) -> dict[str, Any]:
        qty = q(self.base_position_usdt / price, QTY_STEP)
        return {
            "symbol": symbol,
            "state": "BALANCE",
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
            "last_transfer_tick": -999999,
            "last_loss_reduce_tick": -999999,
            "last_transfer_price": None,
            "last_loss_reduce_price": None,
            "tick_count": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }

    def on_tick(self, state: dict[str, Any], price: Decimal) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        state = deepcopy(state)
        state["tick_count"] = int(state.get("tick_count", 0)) + 1
        state["last_price"] = str(price)
        state["high_since_base"] = str(max(d(state["high_since_base"]), price))
        state["low_since_base"] = str(min(d(state["low_since_base"]), price))
        self.mark_to_market(state, price)

        risk_events = self.check_risk(state, price)
        strategy_events: list[dict[str, Any]] = []

        event = self.try_loss_side_reduction(state, price)
        if event is None:
            event = self.try_profit_transfer(state, price)
        if event is None:
            event = self.try_position_recovery(state, price)

        if event is not None:
            strategy_events.append(event)

        state["state"] = self.resolve_state(state, price)
        state["updated_at"] = now_iso()
        self.mark_to_market(state, price)
        return state, strategy_events, risk_events

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
        self.mark_to_market(state, price)
        events: list[dict[str, Any]] = []
        gross_limit = d(state["budget_usdt"]) * d(self.risk["max_gross_exposure_ratio"])
        gross = d(state.get("gross_exposure", "0"))
        if gross > gross_limit:
            events.append({
                "id": self.uid("risk"),
                "timestamp": now_iso(),
                "symbol": state["symbol"],
                "risk_level": "high",
                "risk_type": "MAX_GROSS_EXPOSURE",
                "action_taken": "ONLY_REDUCE",
                "message": "总敞口超过单币种限制，禁止继续加仓。",
            })

        drawdown_limit = d(state["budget_usdt"]) * pct(d(self.risk["max_symbol_drawdown_pct"]))
        total_pnl = d(state["realized_pnl"]) + d(state["long_unrealized_pnl"]) + d(state["short_unrealized_pnl"])
        if total_pnl < -drawdown_limit:
            events.append({
                "id": self.uid("risk"),
                "timestamp": now_iso(),
                "symbol": state["symbol"],
                "risk_level": "high",
                "risk_type": "MAX_SYMBOL_DRAWDOWN",
                "action_taken": "PAUSE_SYMBOL",
                "message": "单币种回撤超过限制。",
            })
        return events

    def try_loss_side_reduction(self, state: dict[str, Any], price: Decimal) -> dict[str, Any] | None:
        cfg = self.events["loss_side_reduction"]
        if not cfg.get("enabled", True):
            return None

        base = d(state["base_price"])
        move_pct = (price / base - Decimal("1")) * Decimal("100")
        trigger = d(cfg["trigger"]["trend_confirm_move_pct_from_base"])
        step = d(cfg["trigger"]["reduce_step_pct"])
        tick_count = int(state["tick_count"])
        cooldown = int(cfg["guard"].get("cooldown_ticks", 0))
        if tick_count - int(state.get("last_loss_reduce_tick", -999999)) < cooldown:
            return None

        if move_pct >= trigger:
            loss_side = "SHORT"
            last_price = d(state["last_loss_reduce_price"] or base * (Decimal("1") + pct(trigger - step)))
            if price < last_price * (Decimal("1") + pct(step)):
                return None
            return self.execute_loss_side_reduce(state, price, "UP", loss_side)

        if move_pct <= -trigger:
            loss_side = "LONG"
            last_price = d(state["last_loss_reduce_price"] or base * (Decimal("1") - pct(trigger - step)))
            if price > last_price * (Decimal("1") - pct(step)):
                return None
            return self.execute_loss_side_reduce(state, price, "DOWN", loss_side)

        return None

    def execute_loss_side_reduce(self, state: dict[str, Any], price: Decimal, direction: str, loss_side: str) -> dict[str, Any] | None:
        cfg = self.events["loss_side_reduction"]
        base_qty = d(state["base_qty"])
        min_qty = base_qty * d(cfg["sizing"]["min_loss_side_position_ratio_of_base"])
        reduce_ratio = d(cfg["sizing"]["reduce_loss_side_ratio"])
        qty_key = "short_qty" if loss_side == "SHORT" else "long_qty"
        current_qty = d(state[qty_key])
        if current_qty <= min_qty:
            return None
        reduce_qty = min(current_qty * reduce_ratio, current_qty - min_qty)
        if reduce_qty <= 0:
            return None

        state_before = state["state"]
        trades: list[dict[str, Any]] = []
        action = "REDUCE_SHORT" if loss_side == "SHORT" else "REDUCE_LONG"
        trades.append(self.apply_trade(state, price, action, q(reduce_qty, QTY_STEP), "LOSS_SIDE_REDUCTION", "confirmed_trend_reduce_loss_side"))
        state["loss_side_reduce_count_in_trend"] = int(state.get("loss_side_reduce_count_in_trend", 0)) + 1
        state["last_loss_reduce_tick"] = state["tick_count"]
        state["last_loss_reduce_price"] = str(price)
        state["state"] = "TREND_UP_REDUCING_SHORT" if direction == "UP" else "TREND_DOWN_REDUCING_LONG"

        return self.strategy_event(
            event_type=f"LOSS_SIDE_REDUCTION_{direction}",
            state_before=state_before,
            state_after=state["state"],
            symbol=state["symbol"],
            direction=direction,
            reason="单边趋势确认，逐步削减亏损腿仓位。",
            trades=trades,
            trigger={"price": f(price), "loss_side": loss_side},
        )

    def try_profit_transfer(self, state: dict[str, Any], price: Decimal) -> dict[str, Any] | None:
        cfg = self.events["profit_transfer"]
        if not cfg.get("enabled", True):
            return None

        base = d(state["base_price"])
        move_pct = (price / base - Decimal("1")) * Decimal("100")
        trend_confirm_pct = d(self.events["loss_side_reduction"]["trigger"]["trend_confirm_move_pct_from_base"])
        if cfg["guard"].get("skip_if_trend_confirmed", True) and abs(move_pct) >= trend_confirm_pct:
            return None

        if abs(move_pct) < d(cfg["trigger"]["min_price_move_pct_from_base"]):
            return None
        if int(state.get("profit_transfer_count_in_trend", 0)) >= int(cfg["guard"]["max_times_per_trend"]):
            return None

        tick_count = int(state["tick_count"])
        cooldown = int(cfg["guard"].get("cooldown_ticks", 0))
        if tick_count - int(state.get("last_transfer_tick", -999999)) < cooldown:
            return None

        direction = "UP" if move_pct > 0 else "DOWN"
        profit_side = "LONG" if direction == "UP" else "SHORT"
        loss_side = "SHORT" if direction == "UP" else "LONG"
        profit_qty = d(state["long_qty"] if profit_side == "LONG" else state["short_qty"])
        if profit_qty <= 0:
            return None

        profit_pnl = d(state["long_unrealized_pnl"] if profit_side == "LONG" else state["short_unrealized_pnl"])
        min_profit = d(state["budget_usdt"]) * pct(d(cfg["trigger"]["min_profit_pct_of_symbol_budget"]))
        if profit_pnl < min_profit:
            return None

        reduce_qty = q(profit_qty * d(cfg["sizing"]["reduce_profit_side_ratio"]), QTY_STEP)
        projected = self.preview_reduce(state, price, profit_side, reduce_qty)
        min_net_profit = d(cfg["sizing"]["min_net_profit_usdt"])
        if projected["net_realized"] < min_net_profit:
            return None

        add_notional = projected["net_realized"] * d(cfg["sizing"]["use_realized_profit_ratio_for_loss_side"])
        max_add_notional = self.base_position_usdt * d(cfg["sizing"]["max_add_loss_side_ratio_of_base_position"])
        add_notional = min(add_notional, max_add_notional)
        if cfg["sizing"].get("restore_loss_side_only_to_base", False):
            loss_qty = d(state["short_qty"] if loss_side == "SHORT" else state["long_qty"])
            restore_capacity = max(Decimal("0"), d(state["base_qty"]) - loss_qty) * price
            add_notional = min(add_notional, restore_capacity)
        if add_notional <= 0:
            return None

        if not self.can_add_notional(state, price, add_notional):
            return None

        state_before = state["state"]
        trades: list[dict[str, Any]] = []
        reduce_action = "REDUCE_LONG" if profit_side == "LONG" else "REDUCE_SHORT"
        add_action = "ADD_SHORT" if loss_side == "SHORT" else "ADD_LONG"
        trades.append(self.apply_trade(state, price, reduce_action, reduce_qty, "REDUCE_PROFIT_SIDE", "profit_transfer_reduce_profit_side"))
        add_qty = q(add_notional / price, QTY_STEP)
        trades.append(self.apply_trade(state, price, add_action, add_qty, "ADD_LOSS_SIDE", "profit_transfer_add_loss_side"))

        state["profit_transfer_count_in_trend"] = int(state.get("profit_transfer_count_in_trend", 0)) + 1
        state["last_transfer_tick"] = state["tick_count"]
        state["last_transfer_price"] = str(price)
        state["trend_extreme_price"] = str(price)
        state["state"] = "TREND_UP" if direction == "UP" else "TREND_DOWN"

        return self.strategy_event(
            event_type=f"PROFIT_TRANSFER_{direction}",
            state_before=state_before,
            state_after=state["state"],
            symbol=state["symbol"],
            direction=direction,
            reason="盈利腿减仓实现净利润，并按配置恢复或增加亏损腿。",
            trades=trades,
            trigger={"profit_side": profit_side, "loss_side": loss_side, "profit_pnl": f(profit_pnl)},
            sizing={"reduce_qty": f(reduce_qty), "add_notional": f(add_notional)},
        )

    def try_position_recovery(self, state: dict[str, Any], price: Decimal) -> dict[str, Any] | None:
        cfg = self.events["position_recovery"]
        if not cfg.get("enabled", True):
            return None

        base_qty = d(state["base_qty"])
        high = d(state["high_since_base"])
        low = d(state["low_since_base"])
        pullback = d(cfg["trigger"]["pullback_pct_from_trend_extreme"])
        restore_ratio = d(cfg["sizing"]["restore_profit_side_ratio"])
        normalize_ratio = d(cfg["sizing"]["normalize_loss_side_ratio"])
        max_restore_qty = base_qty * d(cfg["sizing"]["max_restore_per_tick_ratio"])
        trades: list[dict[str, Any]] = []
        state_before = state["state"]

        if high > d(state["base_price"]) and (high - price) / high * Decimal("100") >= pullback:
            if d(state["long_qty"]) < base_qty and self.can_add_notional(state, price, (base_qty - d(state["long_qty"])) * price):
                add_qty = min((base_qty - d(state["long_qty"])) * restore_ratio, max_restore_qty)
                if add_qty > 0:
                    trades.append(self.apply_trade(state, price, "ADD_LONG", q(add_qty, QTY_STEP), "POSITION_RECOVERY", "pullback_restore_profit_side_long"))
            if d(state["short_qty"]) > base_qty:
                reduce_qty = (d(state["short_qty"]) - base_qty) * normalize_ratio
                if reduce_qty > 0:
                    trades.append(self.apply_trade(state, price, "REDUCE_SHORT", q(reduce_qty, QTY_STEP), "POSITION_RECOVERY", "pullback_normalize_loss_side_short"))
            direction = "UP"
        elif low < d(state["base_price"]) and (price - low) / low * Decimal("100") >= pullback:
            if d(state["short_qty"]) < base_qty and self.can_add_notional(state, price, (base_qty - d(state["short_qty"])) * price):
                add_qty = min((base_qty - d(state["short_qty"])) * restore_ratio, max_restore_qty)
                if add_qty > 0:
                    trades.append(self.apply_trade(state, price, "ADD_SHORT", q(add_qty, QTY_STEP), "POSITION_RECOVERY", "pullback_restore_profit_side_short"))
            if d(state["long_qty"]) > base_qty:
                reduce_qty = (d(state["long_qty"]) - base_qty) * normalize_ratio
                if reduce_qty > 0:
                    trades.append(self.apply_trade(state, price, "REDUCE_LONG", q(reduce_qty, QTY_STEP), "POSITION_RECOVERY", "pullback_normalize_loss_side_long"))
            direction = "DOWN"
        else:
            return None

        if not trades:
            return None

        state["recovery_count_in_trend"] = int(state.get("recovery_count_in_trend", 0)) + 1
        state["state"] = "RECOVERING_FROM_UP" if direction == "UP" else "RECOVERING_FROM_DOWN"
        return self.strategy_event(
            event_type=f"POSITION_RECOVERY_{direction}",
            state_before=state_before,
            state_after=state["state"],
            symbol=state["symbol"],
            direction=direction,
            reason="趋势极值后出现回调或反弹，逐步恢复仓位结构。",
            trades=trades,
            trigger={"price": f(price), "high_since_base": f(high), "low_since_base": f(low)},
        )

    def can_add_notional(self, state: dict[str, Any], price: Decimal, add_notional: Decimal) -> bool:
        gross_limit = d(state["budget_usdt"]) * d(self.risk["max_gross_exposure_ratio"])
        current_gross = (d(state["long_qty"]) + d(state["short_qty"])) * price
        return current_gross + add_notional <= gross_limit

    def preview_reduce(self, state: dict[str, Any], price: Decimal, profit_side: str, qty: Decimal) -> dict[str, Decimal]:
        action = "REDUCE_LONG" if profit_side == "LONG" else "REDUCE_SHORT"
        fill_price = self.fill_price(price, action)
        entry = d(state["long_entry_price"] if profit_side == "LONG" else state["short_entry_price"])
        gross = (fill_price - entry) * qty if profit_side == "LONG" else (entry - fill_price) * qty
        notional = fill_price * qty
        fee = notional * d(self.costs["taker_fee_rate"])
        return {"gross_realized": gross, "fee": fee, "net_realized": gross - fee}

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

    def resolve_state(self, state: dict[str, Any], price: Decimal) -> str:
        if state["state"].startswith("RECOVERING") or state["state"].startswith("TREND_"):
            current = state["state"]
        else:
            current = "BALANCE"
        base = d(state["base_price"])
        move_pct = (price / base - Decimal("1")) * Decimal("100")
        trend_confirm_pct = d(self.events["loss_side_reduction"]["trigger"]["trend_confirm_move_pct_from_base"])
        if move_pct >= trend_confirm_pct:
            return "TREND_UP_REDUCING_SHORT"
        if move_pct <= -trend_confirm_pct:
            return "TREND_DOWN_REDUCING_LONG"
        if move_pct >= d(self.events["profit_transfer"]["trigger"]["min_price_move_pct_from_base"]):
            return "TREND_UP"
        if move_pct <= -d(self.events["profit_transfer"]["trigger"]["min_price_move_pct_from_base"]):
            return "TREND_DOWN"
        target = d(self.events["position_recovery"]["target"]["target_balance_position_distance_pct"])
        base_qty = d(state["base_qty"])
        if base_qty > 0:
            long_dist = abs(d(state["long_qty"]) - base_qty) / base_qty
            short_dist = abs(d(state["short_qty"]) - base_qty) / base_qty
            if long_dist <= target and short_dist <= target:
                return "BALANCE"
        return current

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
            "realized_pnl": f(sum(d(t["realized_pnl"]) for t in trades)),
            "fee_total": f(sum(d(t["fee"]) for t in trades)),
            "slippage_total": f(sum(d(t["slippage_cost"]) for t in trades)),
            "status": "filled",
            "trades": trades,
        }

    def uid(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:16]}"
