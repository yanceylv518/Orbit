from __future__ import annotations

import json
from typing import Any


class MySqlAuditWriter:
    def write(self, cursor, payload: dict[str, Any], ids: dict[str, int]) -> None:
        for item in payload.get("admin_audit_logs", []):
            admin_db_id = ids.get(f"user:{item.get('admin_user_id', 'admin_001')}")
            if not admin_db_id:
                continue
            cursor.execute(
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
