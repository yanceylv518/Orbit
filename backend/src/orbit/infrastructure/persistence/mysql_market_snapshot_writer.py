from __future__ import annotations

from typing import Any


class MySqlMarketSnapshotWriter:
    def write(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy = payload["strategy_instance"]
        strategy_db_id = ids[f"strategy:{strategy['id']}"]
        user_db_id = ids[f"user:{strategy['user_id']}"]
        account_db_id = ids[f"account:{strategy['exchange_account_id']}"]
        for symbol, view in payload.get("symbol_views", {}).items():
            cur.execute(
                """
                INSERT INTO market_snapshots (
                  timestamp, user_id, exchange_account_id, strategy_instance_id, symbol,
                  price, mark_price, state, long_qty, short_qty, long_unrealized_pnl,
                  short_unrealized_pnl, realized_pnl, net_exposure, gross_exposure, equity
                )
                VALUES (CURRENT_TIMESTAMP(6), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_db_id,
                    account_db_id,
                    strategy_db_id,
                    symbol,
                    view["price"],
                    view["price"],
                    view["state"],
                    view["long_qty"],
                    view["short_qty"],
                    view["long_unrealized_pnl"],
                    view["short_unrealized_pnl"],
                    view["realized_pnl"],
                    view["net_exposure"],
                    view["gross_exposure"],
                    view["equity"],
                ),
            )
