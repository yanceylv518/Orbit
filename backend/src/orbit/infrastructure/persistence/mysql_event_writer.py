from __future__ import annotations

import json
from typing import Any


class MySqlEventHistoryWriter:
    def write(self, cursor, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy = payload["strategy_instance"]
        for event in payload.get("strategy_events", []):
            cursor.execute(
                """
                INSERT IGNORE INTO strategy_events (
                  event_uid, timestamp, user_id, exchange_account_id, strategy_instance_id,
                  symbol, event_type, direction, state_before, state_after, trigger_json,
                  sizing_json, action_plan_json, realized_pnl, fee_total, slippage_total,
                  reason, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), CAST(%s AS JSON),
                        CAST(%s AS JSON), %s, %s, %s, %s, %s)
                """,
                (
                    event["id"],
                    event["timestamp"].replace("T", " ").replace("+00:00", ""),
                    ids[f"user:{strategy['user_id']}"],
                    ids[f"account:{strategy['exchange_account_id']}"],
                    ids[f"strategy:{strategy['id']}"],
                    event["symbol"],
                    event["event_type"],
                    event.get("direction"),
                    event.get("state_before"),
                    event.get("state_after"),
                    json.dumps(event.get("trigger", {}), ensure_ascii=False),
                    json.dumps(event.get("sizing", {}), ensure_ascii=False),
                    json.dumps(event.get("trades", []), ensure_ascii=False),
                    event.get("realized_pnl", 0),
                    event.get("fee_total", 0),
                    event.get("slippage_total", 0),
                    event.get("reason", ""),
                    event.get("status", "filled"),
                ),
            )

        for trade in payload.get("trade_events", []):
            cursor.execute(
                """
                INSERT IGNORE INTO trade_events (
                  trade_uid, strategy_event_id, timestamp, user_id, exchange_account_id,
                  strategy_instance_id, symbol, event_type, side, position_side, action,
                  price, fill_price, qty, notional, fee, slippage_cost, funding_fee,
                  realized_pnl, reason, status
                )
                VALUES (
                  %s, (SELECT id FROM strategy_events WHERE event_uid = %s),
                  %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    trade["id"],
                    trade.get("strategy_event_id"),
                    trade["timestamp"].replace("T", " ").replace("+00:00", ""),
                    ids[f"user:{strategy['user_id']}"],
                    ids[f"account:{strategy['exchange_account_id']}"],
                    ids[f"strategy:{strategy['id']}"],
                    trade["symbol"],
                    trade["event_type"],
                    trade["side"],
                    trade["position_side"],
                    trade["action"],
                    trade["price"],
                    trade["fill_price"],
                    trade["qty"],
                    trade["notional"],
                    trade.get("fee", 0),
                    trade.get("slippage_cost", 0),
                    trade.get("funding_fee", 0),
                    trade.get("realized_pnl", 0),
                    trade.get("reason", ""),
                    trade.get("status", "filled"),
                ),
            )
