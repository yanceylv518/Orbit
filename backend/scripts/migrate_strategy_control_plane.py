from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.live_pilot_control import normalize_live_pilot_control
from orbit.application.strategy_control_plane import legacy_tb4_control_plane_projection
from orbit.infrastructure.persistence.strategy_control_plane_writer import (
    MySqlStrategyControlPlaneWriter,
)


REQUIRED_TABLES = {
    "strategy_definitions",
    "strategy_evidence_bundles",
    "strategy_control_instances",
    "portfolio_risk_policies",
    "account_strategy_bindings",
    "runner_leases",
}


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def mysql_password(db: dict) -> str:
    password = db.get("password")
    if db.get("password_env"):
        password = os.environ.get(str(db["password_env"]), password)
    if not password:
        raise SystemExit("Missing MySQL password; configure password_env before migration.")
    return str(password)


def load_persisted_live_control(cur, runtime: dict) -> dict:
    """Use the persisted runtime control as authority; config is only fallback."""
    cur.execute(
        "SELECT payload_json FROM app_runtime_state WHERE state_key = %s",
        ("default",),
    )
    row = cur.fetchone()
    payload = row[0] if row else None
    if isinstance(payload, str):
        payload = json.loads(payload)
    persisted = payload.get("live_pilot_control") if isinstance(payload, dict) else None
    return normalize_live_pilot_control(persisted, runtime)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Idempotently seed the additive ARCH-1 strategy control plane."
    )
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply the seed transaction. Without this flag the script only validates prerequisites.",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    if config.get("storage", {}).get("driver") != "mysql":
        raise SystemExit("storage.driver must be mysql.")
    db = config.get("storage", {}).get("mysql", {})
    pymysql = importlib.import_module("pymysql")
    conn = pymysql.connect(
        host=db.get("host", "127.0.0.1"), port=int(db.get("port", 3306)),
        user=db.get("user", "root"), password=mysql_password(db),
        database=db.get("database", "dynamic_dual_grid"), charset="utf8mb4",
        autocommit=False,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            existing = {str(row[0]) for row in cur.fetchall()}
            missing = sorted(REQUIRED_TABLES - existing)
            if missing:
                raise RuntimeError(
                    "ARCH-1 tables are missing; run backend/scripts/setup_mysql.py first: "
                    + ", ".join(missing)
                )
            control = load_persisted_live_control(cur, config.get("runtime", {}))
            records = legacy_tb4_control_plane_projection(control, lambda: {})
            if args.apply:
                MySqlStrategyControlPlaneWriter().write(cur, records)
            else:
                conn.rollback()
                print("ARCH-1 prerequisites valid; no writes performed (use --apply).")
                return
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("ARCH-1 control-plane seed complete.")


if __name__ == "__main__":
    main()
