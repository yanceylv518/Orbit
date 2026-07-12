from __future__ import annotations

from typing import Any


class MySqlReportWriter:
    def write(self, cursor, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy = payload["strategy_instance"]
        strategy_db_id = ids[f"strategy:{strategy['id']}"]
        user_db_id = ids[f"user:{strategy['user_id']}"]
        account_db_id = ids[f"account:{strategy['exchange_account_id']}"]
        for report in payload.get("daily_reports", []):
            cursor.execute(
                """
                INSERT INTO daily_reports (
                  report_date, user_id, exchange_account_id, strategy_instance_id, symbol,
                  start_equity, end_equity, daily_pnl, daily_pnl_pct, gross_profit,
                  gross_loss, fee_total, slippage_total, funding_total, net_pnl,
                  max_drawdown, long_max_qty, short_max_qty, max_net_exposure,
                  max_gross_exposure, profit_transfer_count, loss_side_reduce_count,
                  position_recovery_count, rebalance_count, trade_count, markdown_path
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  start_equity = VALUES(start_equity), end_equity = VALUES(end_equity),
                  daily_pnl = VALUES(daily_pnl), daily_pnl_pct = VALUES(daily_pnl_pct),
                  fee_total = VALUES(fee_total), slippage_total = VALUES(slippage_total),
                  funding_total = VALUES(funding_total), net_pnl = VALUES(net_pnl),
                  max_drawdown = VALUES(max_drawdown),
                  profit_transfer_count = VALUES(profit_transfer_count),
                  loss_side_reduce_count = VALUES(loss_side_reduce_count),
                  position_recovery_count = VALUES(position_recovery_count),
                  trade_count = VALUES(trade_count), markdown_path = VALUES(markdown_path)
                """,
                (
                    report["date"], user_db_id, account_db_id, strategy_db_id,
                    report.get("symbol", "ALL"), report.get("start_equity", 0),
                    report.get("end_equity", 0), report.get("daily_pnl", 0),
                    report.get("daily_pnl_pct", 0), max(report.get("daily_pnl", 0), 0),
                    min(report.get("daily_pnl", 0), 0), report.get("fee_total", 0),
                    report.get("slippage_total", 0), report.get("funding_total", 0),
                    report.get("net_pnl", 0), report.get("max_drawdown", 0),
                    0, 0, 0, 0, report.get("profit_transfer_count", 0),
                    report.get("loss_side_reduce_count", 0),
                    report.get("position_recovery_count", 0), 0,
                    report.get("trade_count", 0), report.get("markdown_path"),
                ),
            )
