from __future__ import annotations

from copy import deepcopy
from typing import Any

from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.symbol_state_repository import SymbolStateRepository
from orbit.domain.strategy.engine import EventEngine, d, now_iso, q
from orbit.domain.strategy.state_keys import lookup_plan_state, plan_state_key


class SymbolRecoveryService:
    """Admin-only recovery for a latched per-account STOPPED symbol."""

    def __init__(
        self,
        permissions: Any,
        accounts: AccountRepository,
        states: SymbolStateRepository,
        engine: EventEngine,
    ) -> None:
        self.permissions = permissions
        self.accounts = accounts
        self.states = states
        self.engine = engine

    def resume_stopped_symbol(
        self,
        account_id: str,
        symbol: str,
        *,
        actor: str,
        actor_user: dict[str, Any] | None,
        reason: str,
    ) -> dict[str, Any]:
        if not self.permissions.is_admin(actor_user):
            return {"ok": False, "error": "只有管理员可以复核恢复 STOPPED 币种。"}

        account_id = str(account_id or "").strip()
        symbol = str(symbol or "").strip().upper()
        reason = str(reason or "").strip()
        if not account_id or not symbol:
            return {"ok": False, "error": "必须指定交易账户和币种。"}
        if not reason:
            return {"ok": False, "error": "复核恢复必须填写原因。"}
        if not self.accounts.account_by_id(account_id):
            return {"ok": False, "error": "交易账户不存在。"}

        states = self.states.all()
        state = lookup_plan_state(states, account_id, symbol)
        if not state:
            return {"ok": False, "error": "未找到该账户的币种运行状态。"}
        if state.get("state") != "STOPPED":
            return {"ok": False, "error": "该币种当前不是 STOPPED 状态，不能执行恢复。"}

        price = d(state.get("last_price") or state.get("base_price"))
        if price <= 0:
            return {"ok": False, "error": "当前价格无效，无法执行恢复重锚。"}

        self.engine.mark_to_market(state, price)
        current_pnl = (
            d(state.get("realized_pnl"))
            + d(state.get("long_unrealized_pnl"))
            + d(state.get("short_unrealized_pnl"))
        )
        current_equity = d(state.get("equity"))
        if current_equity <= 0:
            return {"ok": False, "error": "当前权益不大于 0，不能恢复策略运行。"}

        before = self.audit_value(account_id, symbol, state)
        previous_base_notional = d(state.get("base_qty")) * d(state.get("base_price"))
        self.engine.lifecycle.reanchor(state, price)
        if previous_base_notional > 0:
            state["base_qty"] = str(q(previous_base_notional / price))

        resumed_at = now_iso()
        state["risk_drawdown_baseline_pnl_usdt"] = str(current_pnl)
        state["risk_drawdown_budget_usdt"] = str(current_equity)
        state["stopped_at"] = None
        state["last_resumed_at"] = resumed_at
        state["last_resumed_by"] = actor
        state["last_resume_reason"] = reason
        state["last_block_code"] = None
        state["updated_at"] = resumed_at
        self.engine.mark_to_market(state, price)

        key = plan_state_key(account_id, symbol)
        if key not in states:
            legacy_key = next((item for item, value in states.items() if value is state), None)
            if legacy_key is not None and legacy_key != key:
                states.pop(legacy_key, None)
            states[key] = state
        self.states.replace_all(states)

        after = self.audit_value(account_id, symbol, state)
        return {
            "ok": True,
            "recovered_symbol": deepcopy(after),
            "_audit": {
                "actor": actor,
                "action_type": "RESUME_STOPPED_SYMBOL",
                "reason": reason,
                "before_value": before,
                "after_value": after,
            },
        }

    @staticmethod
    def audit_value(account_id: str, symbol: str, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": plan_state_key(account_id, symbol),
            "account_id": account_id,
            "symbol": symbol,
            "state": state.get("state"),
            "base_price": state.get("base_price"),
            "last_price": state.get("last_price"),
            "budget_usdt": state.get("budget_usdt"),
            "equity": state.get("equity"),
            "realized_pnl": state.get("realized_pnl"),
            "risk_drawdown_baseline_pnl_usdt": state.get("risk_drawdown_baseline_pnl_usdt", "0"),
            "risk_drawdown_budget_usdt": state.get("risk_drawdown_budget_usdt", state.get("budget_usdt")),
            "stopped_at": state.get("stopped_at"),
            "last_resumed_at": state.get("last_resumed_at"),
        }
