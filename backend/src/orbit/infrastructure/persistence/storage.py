from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any

from orbit.infrastructure.persistence.mysql_audit_writer import MySqlAuditWriter
from orbit.infrastructure.persistence.mysql_event_writer import MySqlEventHistoryWriter
from orbit.infrastructure.persistence.mysql_report_writer import MySqlReportWriter
from orbit.infrastructure.persistence.mysql_config_writer import MySqlConfigWriter
from orbit.infrastructure.persistence.mysql_market_snapshot_writer import MySqlMarketSnapshotWriter
from orbit.infrastructure.persistence.mysql_symbol_state_writer import MySqlSymbolStateWriter


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
        self.event_history_writer = MySqlEventHistoryWriter()
        self.audit_writer = MySqlAuditWriter()
        self.report_writer = MySqlReportWriter()
        self.config_writer = MySqlConfigWriter()
        self.symbol_state_writer = MySqlSymbolStateWriter()
        self.market_snapshot_writer = MySqlMarketSnapshotWriter()

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

    def _connect(self, *, autocommit: bool = True):
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
            autocommit=autocommit,
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

    def save(self, payload: dict[str, Any]) -> None:
        self._ensure_runtime_schema()
        conn = self._connect(autocommit=False)
        try:
            with conn.cursor() as cur:
                ids = self.config_writer.write(cur, payload)
                self.symbol_state_writer.write(cur, payload, ids)
                self.market_snapshot_writer.write(cur, payload, ids)
                self.event_history_writer.write(cur, payload, ids)
                self.audit_writer.write(cur, payload, ids)
                self.report_writer.write(cur, payload, ids)
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
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_symbol_state_columns(self, cur) -> None:
        self._ensure_column(cur, "symbol_states", "base_qty", "DECIMAL(28, 12) NOT NULL DEFAULT 0")
        self._ensure_column(cur, "symbol_states", "trend_exit_candidate_count", "INT NOT NULL DEFAULT 0")
        self._ensure_column(cur, "symbol_states", "last_transfer_tick", "INT NOT NULL DEFAULT -999999")
        self._ensure_column(cur, "symbol_states", "last_loss_reduce_tick", "INT NOT NULL DEFAULT -999999")
        self._ensure_column(cur, "symbol_states", "last_transfer_price", "DECIMAL(28, 12) NULL")
        self._ensure_column(cur, "symbol_states", "last_loss_reduce_price", "DECIMAL(28, 12) NULL")
        self._ensure_column(cur, "symbol_states", "tick_count", "INT NOT NULL DEFAULT 0")
        self._ensure_symbol_state_account_key(cur)

    def _ensure_symbol_state_account_key(self, cur) -> None:
        # 状态键账户化迁移：加 exchange_account_ref 列，唯一键从 (strategy, symbol)
        # 换成 (strategy, account, symbol)，否则多账户同 symbol 会互相覆盖。
        self._ensure_column(cur, "symbol_states", "exchange_account_ref", "VARCHAR(64) NOT NULL DEFAULT ''")
        cur.execute("SHOW INDEX FROM symbol_states WHERE Key_name = %s", ("uk_symbol_states_strategy_account_symbol",))
        if cur.fetchone():
            return
        cur.execute("SHOW INDEX FROM symbol_states WHERE Key_name = %s", ("uk_symbol_states_strategy_symbol",))
        if cur.fetchone():
            cur.execute("ALTER TABLE symbol_states DROP INDEX uk_symbol_states_strategy_symbol")
        cur.execute(
            "ALTER TABLE symbol_states ADD UNIQUE KEY uk_symbol_states_strategy_account_symbol"
            " (strategy_instance_id, exchange_account_ref, symbol)"
        )

    def _ensure_runtime_schema(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                self._ensure_symbol_state_columns(cur)
                self._ensure_column(
                    cur,
                    "account_run_configs",
                    "kline_interval",
                    "VARCHAR(16) NOT NULL DEFAULT '1h' AFTER status",
                )
        finally:
            conn.close()

    def _lookup_id(self, cur, table: str, external_id: str) -> int:
        cur.execute(f"SELECT id FROM {table} WHERE external_id = %s", (external_id,))
        row = cur.fetchone()
        return int(row[0])


def make_state_store(root: Path, storage_config: dict[str, Any], app_config: dict[str, Any] | None = None):
    if storage_config.get("driver") == "mysql":
        return MySqlStateStore(storage_config.get("mysql", {}), app_config)
    return JsonStateStore(root / storage_config.get("json_path", "var/data/runtime_state.json"))


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
