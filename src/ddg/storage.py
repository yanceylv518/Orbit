from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any


class JsonStateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self.path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def load_directory(self) -> dict[str, Any] | None:
        return None


class MySqlStateStore:
    def __init__(self, config: dict[str, Any], app_config: dict[str, Any] | None = None):
        self.config = config
        self.app_config = app_config or {}
        self.driver = self._load_driver()
        self._identity_schema_ready = False
        self._credential_schema_ready = False

    def _load_driver(self):
        try:
            return importlib.import_module("pymysql")
        except Exception as exc:
            raise RuntimeError("PyMySQL is required when storage.driver=mysql.") from exc

    def load(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT payload_json FROM app_runtime_state WHERE state_key = %s", ("default",))
                row = cur.fetchone()
                if not row:
                    return None
                payload = row[0]
                if isinstance(payload, str):
                    return json.loads(payload)
                return payload
        finally:
            conn.close()

    def _connect(self):
        password = self.config.get("password")
        password_env = self.config.get("password_env")
        if password_env:
            password = os.environ.get(password_env, password)
        if password == "YOUR_MYSQL_PASSWORD":
            raise RuntimeError("MySQL password is still a placeholder in config.local.json.")
        return self.driver.connect(
            host=self.config.get("host", "127.0.0.1"),
            port=int(self.config.get("port", 3306)),
            user=self.config.get("user", "root"),
            password=password or "",
            database=self.config.get("database", "dynamic_dual_grid"),
            charset="utf8mb4",
            autocommit=True,
        )

    def ensure_identity_schema(self) -> None:
        if self._identity_schema_ready:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                self._ensure_column(cur, "users", "password_salt", "VARCHAR(64) NULL")
                self._ensure_column(cur, "users", "password_hash", "VARCHAR(255) NULL")
                self._ensure_column(cur, "users", "last_login_at", "TIMESTAMP(6) NULL")
            self._identity_schema_ready = True
        finally:
            conn.close()

    def ensure_credential_schema(self) -> None:
        if self._credential_schema_ready:
            return
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE exchange_accounts MODIFY api_key_ref TEXT NULL")
                cur.execute("ALTER TABLE exchange_accounts MODIFY secret_ref TEXT NULL")
            self._credential_schema_ready = True
        finally:
            conn.close()

    def _ensure_column(self, cur, table: str, column: str, ddl: str) -> None:
        cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
        if cur.fetchone():
            return
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def load_directory(self) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            self.ensure_identity_schema()
            with conn.cursor() as cur:
                users = self._load_users(cur)
                accounts = self._load_accounts(cur)
                strategies = self._load_strategies(cur)
                if not users or not accounts or not strategies:
                    return None
                return {
                    "users": users,
                    "exchange_accounts": accounts,
                    "strategy_instances": strategies,
                }
        finally:
            conn.close()

    def _load_users(self, cur) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT external_id, name, email, role, status
            FROM users
            ORDER BY id
            """
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "email": row[2],
                "role": row[3],
                "status": row[4],
            }
            for row in cur.fetchall()
        ]

    def _load_accounts(self, cur) -> list[dict[str, Any]]:
        self.ensure_credential_schema()
        cur.execute(
            """
            SELECT
              ea.external_id, u.external_id, ea.exchange_name, ea.market_type,
              ea.account_label, ea.testnet, ea.dry_run, ea.api_key_ref,
              ea.api_key_fingerprint, ea.secret_ref, ea.permissions_json,
              ea.hedge_mode_enabled, ea.status
            FROM exchange_accounts ea
            JOIN users u ON u.id = ea.user_id
            ORDER BY ea.id
            """
        )
        accounts = []
        for row in cur.fetchall():
            permissions = row[10]
            if isinstance(permissions, str):
                permissions = json.loads(permissions)
            accounts.append({
                "id": row[0],
                "user_id": row[1],
                "exchange": row[2],
                "market_type": row[3],
                "account_label": row[4],
                "testnet": bool(row[5]),
                "dry_run": bool(row[6]),
                "api_key_ref": row[7],
                "api_key_fingerprint": row[8],
                "secret_ref": row[9],
                "permissions": permissions or {},
                "hedge_mode_required": bool(row[11]),
                "hedge_mode_enabled": bool(row[11]),
                "status": row[12],
            })
        return accounts

    def _load_strategies(self, cur) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT
              si.config_json, si.external_id, u.external_id, ea.external_id,
              si.strategy_name, si.strategy_version, si.mode, si.status,
              si.config_version, si.live_confirm
            FROM strategy_instances si
            JOIN users u ON u.id = si.user_id
            JOIN exchange_accounts ea ON ea.id = si.exchange_account_id
            ORDER BY si.id
            """
        )
        strategies = []
        for row in cur.fetchall():
            config_json = row[0]
            if isinstance(config_json, str):
                strategy = json.loads(config_json)
            else:
                strategy = config_json
            strategy["id"] = row[1]
            strategy["user_id"] = row[2]
            strategy["exchange_account_id"] = row[3]
            strategy["strategy_name"] = row[4]
            strategy["strategy_version"] = row[5]
            strategy["mode"] = row[6]
            strategy["status"] = row[7]
            strategy["config_version"] = row[8]
            if row[9]:
                strategy.setdefault("runtime", {})["live_confirm"] = row[9]
            strategies.append(strategy)
        return strategies

    def auth_user(self, login: str) -> dict[str, Any] | None:
        self.ensure_identity_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT external_id, name, email, role, status, password_salt, password_hash
                    FROM users
                    WHERE external_id = %s OR email = %s
                    LIMIT 1
                    """,
                    (login, login),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0],
                    "name": row[1],
                    "email": row[2],
                    "role": row[3],
                    "status": row[4],
                    "password_salt": row[5],
                    "password_hash": row[6],
                }
        finally:
            conn.close()

    def set_user_password(self, external_id: str, salt: str, password_hash: str) -> None:
        self.ensure_identity_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                    SET password_salt = %s, password_hash = %s
                    WHERE external_id = %s
                    """,
                    (salt, password_hash, external_id),
                )
        finally:
            conn.close()

    def mark_user_login(self, external_id: str) -> None:
        self.ensure_identity_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE users
                    SET last_login_at = CURRENT_TIMESTAMP(6)
                    WHERE external_id = %s
                    """,
                    (external_id,),
                )
        finally:
            conn.close()

    def upsert_exchange_account(self, account: dict[str, Any]) -> None:
        self.ensure_credential_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                user_id = self._lookup_id(cur, "users", account["user_id"])
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
                      exchange_name = VALUES(exchange_name),
                      market_type = VALUES(market_type),
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
                        user_id,
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
        finally:
            conn.close()

    def set_account_credentials(
        self,
        account_id: str,
        user_id: str,
        api_key_ref: str,
        api_key_fingerprint: str,
        secret_ref: str,
    ) -> None:
        self.ensure_credential_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE exchange_accounts ea
                    JOIN users u ON u.id = ea.user_id
                    SET
                      ea.api_key_ref = %s,
                      ea.api_key_fingerprint = %s,
                      ea.secret_ref = %s
                    WHERE ea.external_id = %s
                      AND u.external_id = %s
                    """,
                    (api_key_ref, api_key_fingerprint, secret_ref, account_id, user_id),
                )
                if cur.rowcount <= 0:
                    raise RuntimeError("Account credential update did not match an owned account.")
        finally:
            conn.close()

    def save(self, payload: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                ids = self._upsert_config_records(cur, payload)
                self._upsert_symbol_states(cur, payload, ids)
                self._insert_market_snapshots(cur, payload, ids)
                self._insert_strategy_events(cur, payload, ids)
                self._insert_trade_events(cur, payload, ids)
                self._insert_admin_audit_logs(cur, payload, ids)
                self._upsert_daily_reports(cur, payload, ids)
                cur.execute(
                    """
                    INSERT INTO app_runtime_state (state_key, payload_json, updated_at)
                    VALUES (%s, CAST(%s AS JSON), CURRENT_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE
                      payload_json = VALUES(payload_json),
                      updated_at = CURRENT_TIMESTAMP(6)
                    """,
                    ("default", json.dumps(payload, ensure_ascii=False)),
                )
        finally:
            conn.close()

    def _upsert_config_records(self, cur, payload: dict[str, Any]) -> dict[str, int]:
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

    def _upsert_symbol_states(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy_id = payload["strategy_instance"]["id"]
        strategy_db_id = ids[f"strategy:{strategy_id}"]
        for symbol, state in payload.get("symbol_states", {}).items():
            cur.execute(
                """
                INSERT INTO symbol_states (
                  strategy_instance_id, symbol, state, base_price, high_since_base,
                  low_since_base, trend_extreme_price, last_price, long_qty, short_qty,
                  long_entry_price, short_entry_price, realized_pnl, long_unrealized_pnl,
                  short_unrealized_pnl, fee_total, slippage_total, funding_total,
                  profit_transfer_count_in_trend, loss_side_reduce_count_in_trend,
                  recovery_count_in_trend
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  state = VALUES(state),
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
                  recovery_count_in_trend = VALUES(recovery_count_in_trend)
                """,
                (
                    strategy_db_id,
                    symbol,
                    state["state"],
                    state["base_price"],
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
                ),
            )

    def _insert_market_snapshots(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
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

    def _insert_strategy_events(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy = payload["strategy_instance"]
        for event in payload.get("strategy_events", []):
            cur.execute(
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

    def _insert_trade_events(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy = payload["strategy_instance"]
        for trade in payload.get("trade_events", []):
            cur.execute(
                """
                INSERT IGNORE INTO trade_events (
                  trade_uid, strategy_event_id, timestamp, user_id, exchange_account_id,
                  strategy_instance_id, symbol, event_type, side, position_side, action,
                  price, fill_price, qty, notional, fee, slippage_cost, funding_fee,
                  realized_pnl, reason, status
                )
                VALUES (
                  %s,
                  (SELECT id FROM strategy_events WHERE event_uid = %s),
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

    def _insert_admin_audit_logs(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        for item in payload.get("admin_audit_logs", []):
            admin_external_id = item.get("admin_user_id", "admin_001")
            admin_db_id = ids.get(f"user:{admin_external_id}")
            if not admin_db_id:
                continue
            cur.execute(
                """
                INSERT IGNORE INTO admin_audit_logs (
                  audit_uid, admin_user_id, action_type, target_user_id, target_account_id,
                  target_strategy_id, target_symbol, before_value_json, after_value_json, reason, created_at
                )
                VALUES (%s, %s, %s, NULL, NULL, NULL, %s, CAST(%s AS JSON), CAST(%s AS JSON), %s, %s)
                """,
                (
                    item["id"],
                    admin_db_id,
                    item.get("action_type", "UNKNOWN"),
                    item.get("target_symbol"),
                    json.dumps(item.get("before_value", {}), ensure_ascii=False),
                    json.dumps(item.get("after_value", {}), ensure_ascii=False),
                    item.get("reason", ""),
                    item.get("timestamp", "").replace("T", " ").replace("+00:00", ""),
                ),
            )

    def _upsert_daily_reports(self, cur, payload: dict[str, Any], ids: dict[str, int]) -> None:
        strategy = payload["strategy_instance"]
        strategy_db_id = ids[f"strategy:{strategy['id']}"]
        user_db_id = ids[f"user:{strategy['user_id']}"]
        account_db_id = ids[f"account:{strategy['exchange_account_id']}"]
        for report in payload.get("daily_reports", []):
            cur.execute(
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
                  start_equity = VALUES(start_equity),
                  end_equity = VALUES(end_equity),
                  daily_pnl = VALUES(daily_pnl),
                  daily_pnl_pct = VALUES(daily_pnl_pct),
                  fee_total = VALUES(fee_total),
                  slippage_total = VALUES(slippage_total),
                  funding_total = VALUES(funding_total),
                  net_pnl = VALUES(net_pnl),
                  max_drawdown = VALUES(max_drawdown),
                  profit_transfer_count = VALUES(profit_transfer_count),
                  loss_side_reduce_count = VALUES(loss_side_reduce_count),
                  position_recovery_count = VALUES(position_recovery_count),
                  trade_count = VALUES(trade_count),
                  markdown_path = VALUES(markdown_path)
                """,
                (
                    report["date"],
                    user_db_id,
                    account_db_id,
                    strategy_db_id,
                    report.get("symbol", "ALL"),
                    report.get("start_equity", 0),
                    report.get("end_equity", 0),
                    report.get("daily_pnl", 0),
                    report.get("daily_pnl_pct", 0),
                    max(report.get("daily_pnl", 0), 0),
                    min(report.get("daily_pnl", 0), 0),
                    report.get("fee_total", 0),
                    report.get("slippage_total", 0),
                    report.get("funding_total", 0),
                    report.get("net_pnl", 0),
                    report.get("max_drawdown", 0),
                    0,
                    0,
                    0,
                    0,
                    report.get("profit_transfer_count", 0),
                    report.get("loss_side_reduce_count", 0),
                    report.get("position_recovery_count", 0),
                    0,
                    report.get("trade_count", 0),
                    report.get("markdown_path"),
                ),
            )

    def _lookup_id(self, cur, table: str, external_id: str) -> int:
        cur.execute(f"SELECT id FROM {table} WHERE external_id = %s", (external_id,))
        row = cur.fetchone()
        return int(row[0])


def make_state_store(root: Path, storage_config: dict[str, Any], app_config: dict[str, Any] | None = None):
    if storage_config.get("driver") == "mysql":
        return MySqlStateStore(storage_config.get("mysql", {}), app_config)
    return JsonStateStore(root / storage_config.get("json_path", "data/runtime_state.json"))


def mysql_status() -> dict[str, Any]:
    for module_name in ("pymysql", "mysql.connector"):
        try:
            importlib.import_module(module_name)
            return {
                "available": True,
                "driver": module_name,
                "message": "MySQL Python driver is available.",
            }
        except Exception:
            continue
    return {
        "available": False,
        "driver": None,
        "message": "未安装 Python MySQL 驱动。dry_run 当前使用 JSON fallback；安装 PyMySQL 后可切换 MySQL repository。",
    }
