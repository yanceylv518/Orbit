from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from orbit.application.ports.account_repository import AccountRepository
from orbit.application.ports.account_snapshot_repository import AccountSnapshotRepository
from orbit.application.ports.run_config_repository import RunConfigRepository
from orbit.application.ports.symbol_state_repository import SymbolStateRepository
from orbit.domain.planning.plans import empty_side, group_positions, normalized_symbols, symbol_budget
from orbit.domain.strategy.engine import EventEngine, d, q
from orbit.domain.strategy.exposure import derive_anchor_price
from orbit.domain.strategy.state_keys import lookup_plan_state, plan_state_key


class SymbolStateService:
    """Keeps plan-only symbol lifecycle state in sync with real exchange snapshots."""

    def __init__(
        self,
        strategy: dict[str, Any],
        engine: EventEngine,
        repository: SymbolStateRepository,
        accounts: AccountRepository,
        run_configs: RunConfigRepository,
        snapshots: AccountSnapshotRepository,
    ):
        self.strategy = strategy
        self.engine = engine
        self.repository = repository
        self.accounts = accounts
        self.run_configs = run_configs
        self.snapshots = snapshots

    def refresh_plan_symbol_states(
        self,
        *,
        account_ids: set[str],
    ) -> dict[str, dict[str, Any]]:
        updated = self.repository.all()
        run_config_by_account = {
            item.get("account_id"): item
            for item in self.run_configs.all()
            if item.get("account_id")
        }
        selected_account_ids = {str(account_id) for account_id in account_ids}

        for account in self.accounts.accounts():
            account_id = str(account.get("id", ""))
            if account_id not in selected_account_ids:
                continue
            run_config = run_config_by_account.get(account_id)
            snapshot = self.snapshots.get(account_id)
            if not self.can_refresh_from_snapshot(run_config, snapshot):
                continue

            allowed_symbols = normalized_symbols(run_config, self.strategy)
            positions_by_symbol = group_positions(snapshot.get("positions", []), allowed_symbols)
            is_paper = run_config.get("mode") == "paper"
            for symbol in allowed_symbols:
                sides = positions_by_symbol.get(symbol)
                if not sides:
                    continue
                # 状态键必须带账户维度：两个账户持同一 symbol 时锚点/相位各自独立
                existing = lookup_plan_state(updated, account_id, symbol)
                if is_paper and existing is not None:
                    continue  # paper 模式：虚拟仓位由内核演进，不被快照覆盖
                updated[plan_state_key(account_id, symbol)] = self.plan_symbol_state_from_snapshot(
                    account_id=account_id,
                    run_config=run_config,
                    symbol=symbol,
                    sides=sides,
                    existing_state=existing,
                )
                # 迁移期清理：旧裸 symbol 键（无账户归属）升级后移除，避免双份
                legacy = updated.get(symbol)
                if legacy is not None and legacy.get("account_id") in (None, account_id):
                    updated.pop(symbol, None)
        self.repository.replace_all(updated)
        return updated

    def advance_state_with_price(
        self,
        state: dict[str, Any],
        *,
        price: float | Decimal,
        close_time: int,
    ) -> dict[str, Any]:
        """行情 tick：仅用收盘价推进生命周期，不改仓位（仓位来自账户同步）。"""
        return self.engine.advance_close(state, d(price), close_time=close_time)

    def can_refresh_from_snapshot(
        self,
        run_config: dict[str, Any] | None,
        snapshot: dict[str, Any] | None,
    ) -> bool:
        if not run_config or not snapshot or snapshot.get("status") != "synced":
            return False
        position_mode = snapshot.get("position_mode") or {}
        return position_mode.get("hedge_mode_ok") is not False

    def plan_symbol_state_from_snapshot(
        self,
        *,
        account_id: str,
        run_config: dict[str, Any],
        symbol: str,
        sides: dict[str, dict[str, Decimal]],
        existing_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        long = sides.get("LONG", empty_side())
        short = sides.get("SHORT", empty_side())
        mark_price = long["mark_price"] or short["mark_price"]
        if mark_price <= 0:
            mark_price = long["entry_price"] or short["entry_price"] or Decimal("1")

        budget = symbol_budget(run_config, self.strategy, symbol)
        base_position = d(run_config.get("base_position_usdt", self.strategy["strategy"].get("base_position_usdt", 0)))
        anchor_price = derive_anchor_price(long["entry_price"], short["entry_price"], mark_price)
        state = deepcopy(existing_state or {})
        is_new_state = not state
        if is_new_state:
            state = self.engine.initialize_symbol(symbol, anchor_price, budget)

        state["symbol"] = symbol
        state["account_id"] = account_id
        state["exchange_account_id"] = account_id
        state["source"] = "binance_plan_state"
        state["budget_usdt"] = str(budget)
        state["last_price"] = str(mark_price)
        state["long_qty"] = str(q(long["qty"]))
        state["short_qty"] = str(q(short["qty"]))
        state["long_entry_price"] = str(long["entry_price"] or mark_price)
        state["short_entry_price"] = str(short["entry_price"] or mark_price)
        state["long_unrealized_pnl"] = str(q(long["pnl"]))
        state["short_unrealized_pnl"] = str(q(short["pnl"]))

        if d(state.get("base_price") or 0) <= 0:
            state["base_price"] = str(anchor_price)
        if is_new_state or d(state.get("base_qty") or 0) <= 0:
            base_price = d(state["base_price"])
            state["base_qty"] = str(q(base_position / base_price)) if base_price > 0 else "0"

        state.setdefault("state", "BALANCED")
        state.setdefault("trend_extreme_price", state["base_price"])
        state.setdefault("profit_transfer_count_in_trend", 0)
        state.setdefault("loss_side_reduce_count_in_trend", 0)
        state.setdefault("recovery_count_in_trend", 0)
        state.setdefault("trend_exit_candidate_count", 0)
        state.setdefault("trend_entry_candidate_count", 0)
        state.setdefault("harvested_profit_usdt", "0")
        state.setdefault("averaging_spent_usdt", "0")
        state.setdefault("last_transfer_tick", -999999)
        state.setdefault("last_loss_reduce_tick", -999999)
        state.setdefault("last_transfer_price", None)
        state.setdefault("last_loss_reduce_price", None)
        state.setdefault("regime", "UNKNOWN")
        state.setdefault("regime_stable", "UNKNOWN")
        state.setdefault("regime_raw", "UNKNOWN")
        state.setdefault("regime_candidate", "")
        state.setdefault("regime_candidate_count", 0)
        state.setdefault("regime_price_history", [])
        state.setdefault("regime_features", {})
        state["tick_count"] = int(state.get("tick_count", 0)) + 1
        state["high_since_base"] = str(max(d(state.get("high_since_base") or state["base_price"]), mark_price))
        state["low_since_base"] = str(min(d(state.get("low_since_base") or state["base_price"]), mark_price))

        self.engine.mark_to_market(state, mark_price)
        self.engine.lifecycle.update_trend_tracking(state, mark_price)
        state["state"] = self.engine.lifecycle.resolve_state(state)
        return state
