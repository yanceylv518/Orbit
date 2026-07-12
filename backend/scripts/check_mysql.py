from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TABLES = [
    "users",
    "exchange_accounts",
    "strategy_instances",
    "symbol_allocations",
    "symbol_states",
    "market_snapshots",
    "strategy_events",
    "trade_events",
    "daily_reports",
    "admin_audit_logs",
    "app_runtime_state",
]


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Dynamic Dual Grid MySQL connectivity.")
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        config_path = ROOT / "config" / "config.sample.json"

    pymysql = importlib.import_module("pymysql")
    config = load_config(config_path)
    db = config.get("storage", {}).get("mysql", {})
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

    conn = pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user", "root"),
        password=password,
        database=db.get("database", "dynamic_dual_grid"),
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            print(f"MySQL version: {version}")
            for table in TABLES:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                print(f"{table}: {count}")
            cur.execute("SHOW COLUMNS FROM users LIKE 'password_hash'")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM users WHERE password_hash IS NOT NULL")
                print(f"users_with_password: {cur.fetchone()[0]}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
