from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.exchange.binance import fingerprint


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def mysql_password(db: dict[str, Any]) -> str:
    password = db.get("password")
    password_env = db.get("password_env")
    if password_env:
        password = os.environ.get(password_env, password)
    if password == "YOUR_MYSQL_PASSWORD":
        password = None
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("MySQL password: ")
        else:
            raise SystemExit("Missing MySQL password. Set DDG_MYSQL_PASSWORD first.")
    return password


def bool_arg(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure a Binance Futures account record in MySQL.")
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    parser.add_argument("--user-id", default="user_001")
    parser.add_argument("--account-id", default="binance_live_001")
    parser.add_argument("--label", default="Binance Futures")
    parser.add_argument("--api-key-env", default="BINANCE_API_KEY")
    parser.add_argument("--secret-env", default="BINANCE_API_SECRET")
    parser.add_argument("--testnet", default="true", help="true for demo-fapi, false for production fapi")
    parser.add_argument("--dry-run", default="true", help="true keeps strategy from real order execution")
    parser.add_argument("--hedge-mode-required", default="true")
    parser.add_argument("--attach-strategy", default=None, help="Optional strategy external_id to rebind to this account.")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        config_path = ROOT / "config" / "config.sample.json"
    config = load_config(config_path)
    db = config.get("storage", {}).get("mysql", {})
    api_key = os.environ.get(args.api_key_env)
    api_key_fp = fingerprint(api_key)

    pymysql = importlib.import_module("pymysql")
    conn = pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user", "root"),
        password=mysql_password(db),
        database=db.get("database", "dynamic_dual_grid"),
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE external_id = %s", (args.user_id,))
            row = cur.fetchone()
            if not row:
                raise SystemExit(f"User not found: {args.user_id}")
            user_db_id = row[0]
            cur.execute(
                """
                INSERT INTO exchange_accounts (
                  external_id, user_id, exchange_name, market_type, account_label,
                  testnet, dry_run, api_key_ref, api_key_fingerprint, secret_ref,
                  permissions_json, hedge_mode_enabled, status
                )
                VALUES (%s, %s, 'binance', 'futures', %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s, 'active')
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
                    args.account_id,
                    user_db_id,
                    args.label,
                    bool_arg(args.testnet),
                    bool_arg(args.dry_run),
                    f"env:{args.api_key_env}",
                    api_key_fp,
                    f"env:{args.secret_env}",
                    json.dumps({"read": True, "trade": False}, ensure_ascii=False),
                    bool_arg(args.hedge_mode_required),
                ),
            )
            if args.attach_strategy:
                cur.execute("SELECT id FROM exchange_accounts WHERE external_id = %s", (args.account_id,))
                account_db_id = cur.fetchone()[0]
                cur.execute(
                    """
                    UPDATE strategy_instances
                    SET exchange_account_id = %s,
                        user_id = %s
                    WHERE external_id = %s
                    """,
                    (account_db_id, user_db_id, args.attach_strategy),
                )
    finally:
        conn.close()

    print(f"Configured account {args.account_id} for {args.user_id}.")
    print(f"API key env: {args.api_key_env}; present: {bool(api_key)}; fingerprint: {api_key_fp or '-'}")
    print(f"Secret env: {args.secret_env}; present: {bool(os.environ.get(args.secret_env))}")


if __name__ == "__main__":
    main()
