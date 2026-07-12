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

from orbit.application.auth import hash_password


def ensure_column(cur, table: str, column: str, ddl: str) -> None:
    cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
    if cur.fetchone():
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Set Dynamic Dual Grid user password.")
    parser.add_argument("user_id", help="User external_id, for example admin_001")
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    parser.add_argument("--password", help="New password. Omit to enter securely.")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        config_path = ROOT / "config" / "config.sample.json"
    config = load_config(config_path)
    db = config.get("storage", {}).get("mysql", {})
    password = args.password
    if not password:
        password = getpass.getpass(f"New password for {args.user_id}: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Password confirmation does not match.")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")

    pymysql = importlib.import_module("pymysql")
    salt, password_hash = hash_password(password)
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
            ensure_column(cur, "users", "password_salt", "VARCHAR(64) NULL")
            ensure_column(cur, "users", "password_hash", "VARCHAR(255) NULL")
            ensure_column(cur, "users", "last_login_at", "TIMESTAMP(6) NULL")
            cur.execute(
                """
                UPDATE users
                SET password_salt = %s, password_hash = %s
                WHERE external_id = %s
                """,
                (salt, password_hash, args.user_id),
            )
            if cur.rowcount == 0:
                raise SystemExit(f"User not found: {args.user_id}")
    finally:
        conn.close()
    print(f"Password updated for {args.user_id}.")


if __name__ == "__main__":
    main()
