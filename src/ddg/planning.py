from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import uuid4

from ddg.engine import now_iso, q


def dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def pct(value: Any) -> Decimal:
    return dec(value) / Decimal("100")


def flt(value: Decimal | int | float | str | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def generate_account_execution_plans(
    account: dict[str, Any],
    run_config: dict[str, Any],
    strategy: dict[str, Any],
    snapshot: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    created_at = now_iso()
    common = {
        "account_id": account["id"],
        "user_id": account["user_id"],
        "strategy_id": strategy["id"],
        "created_at": created_at,
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
    for symbol in allowed_symbols:
        sides = positions_by_symbol.get(symbol)
        if not sides:
            continue
        plan = plan_symbol(common, run_config, strategy, snapshot, symbol, sides)
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
) -> dict[str, Any] | None:
    events = strategy["strategy"]["events"]
    long = sides.get("LONG", empty_side())
    short = sides.get("SHORT", empty_side())
    mark_price = long["mark_price"] or short["mark_price"]
    if mark_price <= 0:
        return None

    budget = symbol_budget(run_config, strategy, symbol)
    base_position = dec(run_config.get("base_position_usdt", strategy["strategy"].get("base_position_usdt", 0)))
    base_qty = base_position / mark_price if mark_price > 0 else Decimal("0")
    max_single_order = dec(run_config.get("max_single_order_usdt", 0))

    trigger_context = {
        "snapshot_synced_at": snapshot.get("synced_at"),
        "mark_price": flt(mark_price),
        "long_qty": flt(long["qty"]),
        "short_qty": flt(short["qty"]),
        "long_unrealized_pnl": flt(long["pnl"]),
        "short_unrealized_pnl": flt(short["pnl"]),
        "long_notional": flt(long["notional"]),
        "short_notional": flt(short["notional"]),
        "symbol_budget_usdt": flt(budget),
        "base_position_usdt": flt(base_position),
    }

    loss_plan = loss_side_reduction_plan(
        common, run_config, events["loss_side_reduction"], symbol, mark_price, budget,
        base_qty, long, short, max_single_order, trigger_context,
    )
    if loss_plan:
        return loss_plan

    profit_plan = profit_transfer_plan(
        common, run_config, events["profit_transfer"], events["loss_side_reduction"], symbol,
        mark_price, budget, base_position, long, short, max_single_order, trigger_context,
    )
    if profit_plan:
        return profit_plan

    recovery_plan = position_recovery_plan(
        common, run_config, events["position_recovery"], symbol, mark_price, base_position,
        long, short, max_single_order, trigger_context,
    )
    if recovery_plan:
        return recovery_plan

    return None


def loss_side_reduction_plan(
    common: dict[str, Any],
    run_config: dict[str, Any],
    cfg: dict[str, Any],
    symbol: str,
    price: Decimal,
    budget: Decimal,
    base_qty: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
    max_single_order: Decimal,
    trigger_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not cfg.get("enabled", True):
        return None
    trend_loss = budget * pct(cfg["trigger"]["trend_confirm_move_pct_from_base"])
    reduce_ratio = dec(cfg["sizing"]["reduce_loss_side_ratio"])
    min_qty = base_qty * dec(cfg["sizing"]["min_loss_side_position_ratio_of_base"])

    if short["qty"] > min_qty and short["pnl"] <= -trend_loss and long["pnl"] >= 0:
        qty = min(short["qty"] * reduce_ratio, short["qty"] - min_qty)
        action = build_action("REDUCE_SHORT", "SHORT", qty, price, max_single_order, "单边上涨确认，削减亏损空头。")
        return build_plan(common, symbol, "LOSS_SIDE_REDUCTION_UP", "UP", "单边趋势确认下的亏损仓位减仓。", [action], trigger_context, run_config)

    if long["qty"] > min_qty and long["pnl"] <= -trend_loss and short["pnl"] >= 0:
        qty = min(long["qty"] * reduce_ratio, long["qty"] - min_qty)
        action = build_action("REDUCE_LONG", "LONG", qty, price, max_single_order, "单边下跌确认，削减亏损多头。")
        return build_plan(common, symbol, "LOSS_SIDE_REDUCTION_DOWN", "DOWN", "单边趋势确认下的亏损仓位减仓。", [action], trigger_context, run_config)

    return None


def profit_transfer_plan(
    common: dict[str, Any],
    run_config: dict[str, Any],
    cfg: dict[str, Any],
    loss_cfg: dict[str, Any],
    symbol: str,
    price: Decimal,
    budget: Decimal,
    base_position: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
    max_single_order: Decimal,
    trigger_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not cfg.get("enabled", True):
        return None
    min_profit = budget * pct(cfg["trigger"]["min_profit_pct_of_symbol_budget"])
    trend_loss = budget * pct(loss_cfg["trigger"]["trend_confirm_move_pct_from_base"])
    reduce_ratio = dec(cfg["sizing"]["reduce_profit_side_ratio"])
    add_ratio = dec(cfg["sizing"]["use_realized_profit_ratio_for_loss_side"])
    max_add = base_position * dec(cfg["sizing"]["max_add_loss_side_ratio_of_base_position"])

    if long["qty"] > 0 and long["pnl"] >= min_profit and short["pnl"] > -trend_loss:
        reduce_qty = long["qty"] * reduce_ratio
        add_notional = min(max(long["pnl"], Decimal("0")) * add_ratio, max_add)
        actions = [
            build_action("REDUCE_LONG", "LONG", reduce_qty, price, max_single_order, "利润搬运：盈利多头减仓锁定净利润。"),
        ]
        if add_notional > 0:
            actions.append(build_action("ADD_SHORT", "SHORT", add_notional / price, price, max_single_order, "利润搬运：用已实现利润恢复或增加空头。"))
        return build_plan(common, symbol, "PROFIT_TRANSFER_UP", "UP", "盈利腿减仓，并按配置恢复亏损腿。", actions, trigger_context, run_config)

    if short["qty"] > 0 and short["pnl"] >= min_profit and long["pnl"] > -trend_loss:
        reduce_qty = short["qty"] * reduce_ratio
        add_notional = min(max(short["pnl"], Decimal("0")) * add_ratio, max_add)
        actions = [
            build_action("REDUCE_SHORT", "SHORT", reduce_qty, price, max_single_order, "利润搬运：盈利空头减仓锁定净利润。"),
        ]
        if add_notional > 0:
            actions.append(build_action("ADD_LONG", "LONG", add_notional / price, price, max_single_order, "利润搬运：用已实现利润恢复或增加多头。"))
        return build_plan(common, symbol, "PROFIT_TRANSFER_DOWN", "DOWN", "盈利腿减仓，并按配置恢复亏损腿。", actions, trigger_context, run_config)

    return None


def position_recovery_plan(
    common: dict[str, Any],
    run_config: dict[str, Any],
    cfg: dict[str, Any],
    symbol: str,
    price: Decimal,
    base_position: Decimal,
    long: dict[str, Decimal],
    short: dict[str, Decimal],
    max_single_order: Decimal,
    trigger_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not cfg.get("enabled", True) or base_position <= 0:
        return None
    target_distance = dec(cfg["target"]["target_balance_position_distance_pct"])
    restore_ratio = dec(cfg["sizing"]["restore_profit_side_ratio"])
    normalize_ratio = dec(cfg["sizing"]["normalize_loss_side_ratio"])
    long_gap = long["notional"] - base_position
    short_gap = short["notional"] - base_position
    distance = abs(long["notional"] - short["notional"]) / base_position if base_position else Decimal("0")
    if distance <= target_distance:
        return None

    actions: list[dict[str, Any]] = []
    if long_gap < 0:
        actions.append(build_action("ADD_LONG", "LONG", abs(long_gap) * restore_ratio / price, price, max_single_order, "仓位恢复：补回偏低的多头。"))
    if short_gap < 0:
        actions.append(build_action("ADD_SHORT", "SHORT", abs(short_gap) * restore_ratio / price, price, max_single_order, "仓位恢复：补回偏低的空头。"))
    if long_gap > 0:
        actions.append(build_action("REDUCE_LONG", "LONG", long_gap * normalize_ratio / price, price, max_single_order, "仓位恢复：压回偏高的多头。"))
    if short_gap > 0:
        actions.append(build_action("REDUCE_SHORT", "SHORT", short_gap * normalize_ratio / price, price, max_single_order, "仓位恢复：压回偏高的空头。"))

    actions = [item for item in actions if item["quantity"] > 0]
    if not actions:
        return None
    direction = "UP" if long["notional"] >= short["notional"] else "DOWN"
    return build_plan(common, symbol, f"POSITION_RECOVERY_{direction}", direction, "仓位偏离目标结构，生成恢复计划。", actions, trigger_context, run_config)


def build_plan(
    common: dict[str, Any],
    symbol: str,
    event_type: str,
    direction: str,
    reason: str,
    actions: list[dict[str, Any]],
    trigger_context: dict[str, Any],
    run_config: dict[str, Any],
) -> dict[str, Any]:
    actions = apply_run_guards(actions, run_config)
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
        "risk_checks": risk_checks(actions, run_config, blocked),
        "trigger": trigger_context,
    }


def build_action(action: str, position_side: str, qty: Decimal, price: Decimal, max_single_order: Decimal, reason: str) -> dict[str, Any]:
    qty = max(Decimal("0"), qty)
    notional = qty * price
    capped = False
    if max_single_order > 0 and notional > max_single_order:
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
        "reason": reason,
    }


def apply_run_guards(actions: list[dict[str, Any]], run_config: dict[str, Any]) -> list[dict[str, Any]]:
    allow_add = bool(run_config.get("allow_add_position", False))
    reduce_only_mode = bool(run_config.get("allow_reduce_only", True))
    mode = run_config.get("mode", "plan_only")
    guarded = []
    for action in actions:
        item = dict(action)
        if item["quantity"] <= 0 or item["notional_usdt"] <= 0:
            item["status"] = "blocked"
            item["block_reason"] = "计划数量为 0。"
        elif item["action"].startswith("ADD_") and (reduce_only_mode or not allow_add):
            item["status"] = "blocked"
            item["block_reason"] = "当前账户运行配置禁止新增仓位。"
        elif mode != "plan_only":
            item["status"] = "blocked"
            item["block_reason"] = "第一阶段仅允许 plan_only 模式。"
        guarded.append(item)
    return guarded


def risk_checks(actions: list[dict[str, Any]], run_config: dict[str, Any], blocked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"name": "plan_only", "ok": run_config.get("mode") == "plan_only", "message": "第一阶段只生成执行计划，不下单。"},
        {"name": "reduce_only_guard", "ok": not any(a["action"].startswith("ADD_") and a.get("status") == "planned" for a in actions), "message": "默认只允许减仓计划。"},
        {"name": "blocked_actions", "ok": not blocked, "message": f"{len(blocked)} 个动作被风控拦截。"},
    ]


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
