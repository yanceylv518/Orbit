from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def mysql_connection(config: dict[str, Any]):
    pymysql = importlib.import_module("pymysql")
    db = config.get("storage", {}).get("mysql", {})
    password = db.get("password")
    password_env = db.get("password_env")
    if password_env:
        password = os.environ.get(password_env, password)
    return pymysql.connect(
        host=db.get("host", "127.0.0.1"),
        port=int(db.get("port", 3306)),
        user=db.get("user", "root"),
        password=password or "",
        database=db.get("database", "dynamic_dual_grid"),
        charset="utf8mb4",
        autocommit=True,
    )


def strip_runtime_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["tick_index"] = 0
    next_payload["running"] = False
    next_payload["symbol_states"] = {}
    next_payload["symbol_views"] = {}
    next_payload["strategy_events"] = []
    next_payload["trade_events"] = []
    next_payload["risk_events"] = []
    next_payload["execution_plans"] = []
    next_payload["daily_reports"] = []
    next_payload["price_history"] = {}
    next_payload["metric_history"] = []
    next_payload["symbol_metric_history"] = {}
    strategy = dict(next_payload.get("strategy_instance") or {})
    if strategy:
        strategy["mode"] = "read_only"
        strategy["status"] = "paused"
        next_payload["strategy_instance"] = strategy
    return next_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove seeded dry-run/mock runtime data from MySQL.")
    parser.add_argument("--config", default=str(ROOT / "config.local.json"))
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        config_path = ROOT / "config" / "config.sample.json"
    config = load_config(config_path)

    conn = mysql_connection(config)
    try:
        with conn.cursor() as cur:
            for table in (
                "trade_events",
                "strategy_events",
                "risk_events",
                "market_snapshots",
                "symbol_states",
                "daily_reports",
            ):
                cur.execute(f"DELETE FROM {table}")

            cur.execute("SELECT payload_json FROM app_runtime_state WHERE state_key = %s", ("default",))
            row = cur.fetchone()
            if row:
                payload = row[0]
                if isinstance(payload, str):
                    payload = json.loads(payload)
                payload = strip_runtime_payload(payload)
                cur.execute(
                    """
                    UPDATE app_runtime_state
                    SET payload_json = CAST(%s AS JSON)
                    WHERE state_key = %s
                    """,
                    (json.dumps(payload, ensure_ascii=False), "default"),
                )

            cur.execute(
                """
                UPDATE strategy_instances
                SET mode = 'read_only', status = 'paused'
                WHERE mode = 'dry_run'
                """
            )
            cur.execute(
                """
                UPDATE exchange_accounts
                SET account_label = 'Binance Futures Read Only'
                WHERE external_id = 'binance_dry_run_001'
                  AND account_label LIKE '%Dry Run%'
                """
            )
        print("Mock runtime data removed. Users, accounts, strategies, and Binance snapshots are kept.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
