from __future__ import annotations

import argparse
import getpass
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def mysql_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("storage", {}).get("mysql", {})


def mysql_password(config: dict[str, Any]) -> str:
    password = config.get("password")
    password_env = config.get("password_env")
    if password_env:
        password = os.environ.get(password_env, password)
    if password == "YOUR_MYSQL_PASSWORD":
        password = None
    if not password:
        if sys.stdin.isatty():
            password = getpass.getpass("MySQL password: ")
        else:
            raise SystemExit(
                "Missing MySQL password. Set DDG_MYSQL_PASSWORD in your shell, "
                "or run this script from an interactive PowerShell window."
            )
    return password


def split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    escape = False
    for char in sql:
        current.append(char)
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
            continue
        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current.clear()
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def ensure_column(cur, table: str, column: str, ddl: str) -> None:
    cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
    if cur.fetchone():
        return
    cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def run_light_migrations(cur) -> None:
    ensure_column(cur, "users", "password_salt", "VARCHAR(64) NULL")
    ensure_column(cur, "users", "password_hash", "VARCHAR(255) NULL")
    ensure_column(cur, "users", "last_login_at", "TIMESTAMP(6) NULL")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize Dynamic Dual Grid MySQL schema.")
    default_config = ROOT / "config.local.json"
    if not default_config.exists():
        default_config = ROOT / "config.sample.json"
    parser.add_argument("--config", default=str(default_config))
    parser.add_argument("--schema", default=str(ROOT / "sql" / "schema.sql"))
    args = parser.parse_args()

    pymysql = importlib.import_module("pymysql")
    config = load_config(Path(args.config))
    db = mysql_config(config)
    password = mysql_password(db)

    conn = pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user", "root"),
        password=password,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        sql = Path(args.schema).read_text(encoding="utf-8")
        statements = split_sql(sql)
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
            run_light_migrations(cur)
        print(f"Executed {len(statements)} schema statements.")
        print(f"Database ready: {db.get('database', 'dynamic_dual_grid')}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
