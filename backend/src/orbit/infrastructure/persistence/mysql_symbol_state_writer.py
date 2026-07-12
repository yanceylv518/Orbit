from __future__ import annotations

from typing import Any


class MySqlSymbolStateWriter:
    def write(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy_id = payload["strategy_instance"]["id"]
        strategy_db_id = ids[f"strategy:{strategy_id}"]
        for key, state in payload.get("symbol_states", {}).items():
            symbol = str(state.get("symbol") or key.split("::")[-1])
            account_ref = str(state.get("account_id") or state.get("exchange_account_id") or "")
            cur.execute(
                """
                INSERT INTO symbol_states (
                  strategy_instance_id, exchange_account_ref, symbol, state, base_price, base_qty, high_since_base,
                  low_since_base, trend_extreme_price, last_price, long_qty, short_qty,
                  long_entry_price, short_entry_price, realized_pnl, long_unrealized_pnl,
                  short_unrealized_pnl, fee_total, slippage_total, funding_total,
                  profit_transfer_count_in_trend, loss_side_reduce_count_in_trend,
                  recovery_count_in_trend, trend_exit_candidate_count, last_transfer_tick,
                  last_loss_reduce_tick, last_transfer_price, last_loss_reduce_price, tick_count
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  state = VALUES(state),
                  base_price = VALUES(base_price),
                  base_qty = VALUES(base_qty),
                  high_since_base = VALUES(high_since_base),
                  low_since_base = VALUES(low_since_base),
                  trend_extreme_price = VALUES(trend_extreme_price),
                  last_price = VALUES(last_price),
                  long_qty = VALUES(long_qty),
                  short_qty = VALUES(short_qty),
                  long_entry_price = VALUES(long_entry_price),
                  short_entry_price = VALUES(short_entry_price),
                  realized_pnl = VALUES(realized_pnl),
                  long_unrealized_pnl = VALUES(long_unrealized_pnl),
                  short_unrealized_pnl = VALUES(short_unrealized_pnl),
                  fee_total = VALUES(fee_total),
                  slippage_total = VALUES(slippage_total),
                  funding_total = VALUES(funding_total),
                  profit_transfer_count_in_trend = VALUES(profit_transfer_count_in_trend),
                  loss_side_reduce_count_in_trend = VALUES(loss_side_reduce_count_in_trend),
                  recovery_count_in_trend = VALUES(recovery_count_in_trend),
                  trend_exit_candidate_count = VALUES(trend_exit_candidate_count),
                  last_transfer_tick = VALUES(last_transfer_tick),
                  last_loss_reduce_tick = VALUES(last_loss_reduce_tick),
                  last_transfer_price = VALUES(last_transfer_price),
                  last_loss_reduce_price = VALUES(last_loss_reduce_price),
                  tick_count = VALUES(tick_count)
                """,
                (
                    strategy_db_id,
                    account_ref,
                    symbol,
                    state["state"],
                    state["base_price"],
                    state.get("base_qty", 0),
                    state.get("high_since_base"),
                    state.get("low_since_base"),
                    state.get("trend_extreme_price"),
                    state.get("last_price"),
                    state.get("long_qty", 0),
                    state.get("short_qty", 0),
                    state.get("long_entry_price"),
                    state.get("short_entry_price"),
                    state.get("realized_pnl", 0),
                    state.get("long_unrealized_pnl", 0),
                    state.get("short_unrealized_pnl", 0),
                    state.get("fee_total", 0),
                    state.get("slippage_total", 0),
                    state.get("funding_total", 0),
                    state.get("profit_transfer_count_in_trend", 0),
                    state.get("loss_side_reduce_count_in_trend", 0),
                    state.get("recovery_count_in_trend", 0),
                    state.get("trend_exit_candidate_count", 0),
                    state.get("last_transfer_tick", -999999),
                    state.get("last_loss_reduce_tick", -999999),
                    state.get("last_transfer_price"),
                    state.get("last_loss_reduce_price"),
                    state.get("tick_count", 0),
                ),
            )
