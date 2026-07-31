from __future__ import annotations

import argparse
from copy import deepcopy
import getpass
import importlib
import json
import os
from pathlib import Path
import sys
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.auth import hash_password
from orbit.infrastructure.persistence.mysql_config_writer import MySqlConfigWriter


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def mysql_password(db: dict[str, Any]) -> str:
    password = db.get("password")
    password_env = db.get("password_env")
    if password_env:
        password = os.environ.get(password_env, password)
    if not password:
        password = getpass.getpass("MySQL password: ")
    if not password:
        raise SystemExit("Missing MySQL password.")
    return str(password)


def user_mapping(values: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        source, separator, target = value.partition("=")
        source = source.strip()
        target = target.strip()
        if separator != "=" or not source or not target:
            raise SystemExit(f"Invalid --map-user value: {value!r}; expected OLD=NEW.")
        mapping[source] = target
    return mapping


def migration_payload(config: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    users = deepcopy(config.get("users") or [])
    accounts = deepcopy(config.get("exchange_accounts") or [])
    strategies = deepcopy(config.get("strategy_instances") or [])
    run_configs = deepcopy(config.get("account_run_configs") or [])
    if not users or not accounts or len(strategies) != 1:
        raise SystemExit(
            "Config directory must contain users, exchange_accounts, and exactly one "
            "strategy instance before migration."
        )
    for user in users:
        user["id"] = mapping.get(str(user["id"]), str(user["id"]))
    deduplicated_users: dict[str, dict[str, Any]] = {}
    for user in users:
        deduplicated_users[str(user["id"])] = user
    for account in accounts:
        account["user_id"] = mapping.get(
            str(account["user_id"]), str(account["user_id"])
        )
    for strategy in strategies:
        strategy["user_id"] = mapping.get(
            str(strategy["user_id"]), str(strategy["user_id"])
        )
    return {
        "users": list(deduplicated_users.values()),
        "exchange_accounts": accounts,
        "strategy_instance": strategies[0],
        "account_run_configs": run_configs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotently migrate the configured Orbit directory to MySQL. "
            "Existing password hashes are preserved."
        )
    )
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    parser.add_argument(
        "--map-user",
        action="append",
        default=[],
        metavar="OLD=NEW",
        help="Map a configured user ID to an existing production user ID.",
    )
    parser.add_argument(
        "--set-admin-password",
        action="store_true",
        help="Prompt for and replace the selected administrator password.",
    )
    parser.add_argument("--admin-user-id", default="admin_001")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    if config.get("storage", {}).get("driver") != "mysql":
        raise SystemExit("storage.driver must be mysql.")
    db = config.get("storage", {}).get("mysql", {})
    mapping = user_mapping(args.map_user)
    payload = migration_payload(config, mapping)
    admin_user_id = mapping.get(
        args.admin_user_id, args.admin_user_id
    )

    pymysql = importlib.import_module("pymysql")
    conn = pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user", "root"),
        password=mysql_password(db),
        database=db.get("database", "dynamic_dual_grid"),
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT external_id, name, email, role, status
                FROM users
                """
            )
            existing_users = {
                str(row[0]): {
                    "id": row[0],
                    "name": row[1],
                    "email": row[2],
                    "role": row[3],
                    "status": row[4],
                }
                for row in cur.fetchall()
            }
            payload["users"] = [
                existing_users.get(str(user["id"]), user)
                for user in payload["users"]
            ]
            MySqlConfigWriter().write(cur, payload)

            if args.set_admin_password:
                password = getpass.getpass(f"New password for {admin_user_id}: ")
                confirmation = getpass.getpass("Confirm password: ")
                if password != confirmation:
                    raise SystemExit("Password confirmation does not match.")
                if len(password) < 8:
                    raise SystemExit("Password must be at least 8 characters.")
                salt, password_hash = hash_password(password)
                cur.execute(
                    """
                    UPDATE users
                    SET password_salt = %s, password_hash = %s
                    WHERE external_id = %s
                    """,
                    (salt, password_hash, admin_user_id),
                )

            cur.execute(
                """
                SELECT role, status, password_hash
                FROM users
                WHERE external_id = %s
                """,
                (admin_user_id,),
            )
            admin = cur.fetchone()
            if not admin or admin[0] not in ("admin", "super_admin"):
                raise RuntimeError(f"Administrator not found: {admin_user_id}")
            if admin[1] != "active":
                raise RuntimeError(f"Administrator is not active: {admin_user_id}")
            if not admin[2]:
                raise RuntimeError(
                    f"Administrator has no password: {admin_user_id}; "
                    "rerun with --set-admin-password."
                )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("MySQL directory migration complete.")
    print(f"Administrator: {admin_user_id}")
    print(f"Users: {len(payload['users'])}")
    print(f"Accounts: {len(payload['exchange_accounts'])}")
    print("Strategies: 1")


if __name__ == "__main__":
    main()
