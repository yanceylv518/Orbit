from __future__ import annotations

import json
from typing import Any


class MySqlConfigWriter:
    def write(self, cur, payload: dict[str, Any]) -> dict[str, int]:
        ids: dict[str, int] = {}
        users = payload.get("users", [])
        for user in users:
            cur.execute(
                """
                INSERT INTO users (external_id, name, email, role, status)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  name = VALUES(name),
                  email = VALUES(email),
                  role = VALUES(role),
                  status = VALUES(status)
                """,
                (
                    user["id"],
                    user.get("name", user["id"]),
                    user.get("email"),
                    user.get("role", "user"),
                    user.get("status", "active"),
                ),
            )
            ids[f"user:{user['id']}"] = self._lookup_id(cur, "users", user["id"])

        for account in payload.get("exchange_accounts", []):
            user_db_id = ids[f"user:{account['user_id']}"]
            cur.execute(
                """
                INSERT INTO exchange_accounts (
                  external_id, user_id, exchange_name, market_type, account_label,
                  testnet, dry_run, api_key_ref, api_key_fingerprint, secret_ref,
                  permissions_json, hedge_mode_enabled, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s, %s)
                ON DUPLICATE KEY UPDATE
                  user_id = VALUES(user_id),
                  account_label = VALUES(account_label),
                  testnet = VALUES(testnet),
                  dry_run = VALUES(dry_run),
                  api_key_ref = VALUES(api_key_ref),
                  api_key_fingerprint = VALUES(api_key_fingerprint),
                  secret_ref = VALUES(secret_ref),
                  permissions_json = VALUES(permissions_json),
                  hedge_mode_enabled = VALUES(hedge_mode_enabled),
                  status = VALUES(status)
                """,
                (
                    account["id"],
                    user_db_id,
                    account.get("exchange", "binance"),
                    account.get("market_type", "futures"),
                    account.get("account_label", account["id"]),
                    bool(account.get("testnet", True)),
                    bool(account.get("dry_run", True)),
                    account.get("api_key_ref"),
                    account.get("api_key_fingerprint"),
                    account.get("secret_ref"),
                    json.dumps(account.get("permissions", {}), ensure_ascii=False),
                    bool(account.get("hedge_mode_enabled", account.get("hedge_mode_required", False))),
                    account.get("status", "active"),
                ),
            )
            ids[f"account:{account['id']}"] = self._lookup_id(cur, "exchange_accounts", account["id"])

        strategy = payload["strategy_instance"]
        user_db_id = ids[f"user:{strategy['user_id']}"]
        account_db_id = ids[f"account:{strategy['exchange_account_id']}"]
        cur.execute(
            """
            INSERT INTO strategy_instances (
              external_id, user_id, exchange_account_id, strategy_name, strategy_version,
              mode, status, config_version, config_json, live_confirm
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s)
            ON DUPLICATE KEY UPDATE
              user_id = VALUES(user_id),
              exchange_account_id = VALUES(exchange_account_id),
              strategy_name = VALUES(strategy_name),
              strategy_version = VALUES(strategy_version),
              mode = VALUES(mode),
              status = VALUES(status),
              config_json = VALUES(config_json),
              live_confirm = VALUES(live_confirm)
            """,
            (
                strategy["id"],
                user_db_id,
                account_db_id,
                strategy.get("strategy_name", "Dynamic Dual Grid"),
                strategy.get("strategy_version", "v1"),
                strategy.get("mode", "dry_run"),
                strategy.get("status", "running"),
                strategy.get("config_version", "v1"),
                json.dumps(strategy, ensure_ascii=False),
                strategy.get("runtime", {}).get("live_confirm"),
            ),
        )
        ids[f"strategy:{strategy['id']}"] = self._lookup_id(cur, "strategy_instances", strategy["id"])

        for run_config in payload.get("account_run_configs", []):
            account_key = f"account:{run_config['account_id']}"
            strategy_key = f"strategy:{run_config.get('strategy_id', strategy['id'])}"
            if account_key not in ids or strategy_key not in ids:
                continue
            cur.execute(
                """
                INSERT INTO account_run_configs (
                  external_id, exchange_account_id, strategy_instance_id,
                  enabled, mode, status, kline_interval, symbols_json,
                  symbol_budget_json, base_position_usdt, max_single_order_usdt,
                  allow_reduce_only, allow_add_position, allow_market_orders
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON),
                        CAST(%s AS JSON), %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  enabled = VALUES(enabled), mode = VALUES(mode), status = VALUES(status),
                  kline_interval = VALUES(kline_interval), symbols_json = VALUES(symbols_json),
                  symbol_budget_json = VALUES(symbol_budget_json),
                  base_position_usdt = VALUES(base_position_usdt),
                  max_single_order_usdt = VALUES(max_single_order_usdt),
                  allow_reduce_only = VALUES(allow_reduce_only),
                  allow_add_position = VALUES(allow_add_position),
                  allow_market_orders = VALUES(allow_market_orders)
                """,
                (
                    run_config.get("id", f"run_{run_config['account_id']}"),
                    ids[account_key], ids[strategy_key],
                    bool(run_config.get("enabled", True)), run_config.get("mode", "plan_only"),
                    run_config.get("status", "active"), run_config.get("interval", "1h"),
                    json.dumps(run_config.get("symbols", []), ensure_ascii=False),
                    json.dumps(run_config.get("symbol_budget_usdt", {}), ensure_ascii=False),
                    run_config.get("base_position_usdt", 0), run_config.get("max_single_order_usdt", 0),
                    bool(run_config.get("allow_reduce_only", True)),
                    bool(run_config.get("allow_add_position", False)),
                    False,
                ),
            )

        for symbol, budget in strategy.get("symbol_budget_usdt", {}).items():
            cur.execute(
                """
                INSERT INTO symbol_allocations (
                  strategy_instance_id, symbol, budget_usdt, base_position_usdt,
                  max_symbol_drawdown_pct, max_gross_exposure_ratio, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  budget_usdt = VALUES(budget_usdt),
                  base_position_usdt = VALUES(base_position_usdt),
                  max_symbol_drawdown_pct = VALUES(max_symbol_drawdown_pct),
                  max_gross_exposure_ratio = VALUES(max_gross_exposure_ratio),
                  status = VALUES(status)
                """,
                (
                    ids[f"strategy:{strategy['id']}"],
                    symbol,
                    budget,
                    strategy["strategy"]["base_position_usdt"],
                    strategy["strategy"]["risk"]["max_symbol_drawdown_pct"],
                    strategy["strategy"]["risk"]["max_gross_exposure_ratio"],
                    "active",
                ),
            )
        return ids

    def _lookup_id(self, cur, table: str, external_id: str) -> int:
        cur.execute(f"SELECT id FROM {table} WHERE external_id = %s", (external_id,))
        row = cur.fetchone()
        return int(row[0])
