from __future__ import annotations

import json
from typing import Any

from orbit.infrastructure.persistence.strategy_control_plane import snapshot_from_records


class MySqlStrategyControlPlaneWriter:
    """Idempotent ARCH-1 seed writer; it never mutates legacy execution tables."""

    def write(self, cur: Any, records: dict[str, Any]) -> None:
        records = snapshot_from_records(records).as_dict()
        definition_ids: dict[str, int] = {}
        for definition in records.get("definitions") or []:
            cur.execute(
                """
                INSERT INTO strategy_definitions (
                  external_id, family, version, status, implementation,
                  definition_hash, spec_sha256, definition_json, read_only
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, CAST(%s AS JSON), %s)
                ON DUPLICATE KEY UPDATE external_id = VALUES(external_id)
                """,
                (
                    definition["id"], definition["family"], definition["version"],
                    definition["status"], definition["implementation"],
                    definition["definition_hash"], definition.get("spec_sha256"),
                    _json(definition.get("definition") or {}),
                    bool(definition.get("read_only")),
                ),
            )
            cur.execute(
                """
                SELECT id, definition_hash, spec_sha256
                FROM strategy_definitions
                WHERE external_id = %s AND version = %s
                """,
                (definition["id"], definition["version"]),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"strategy definition was not persisted: {definition['id']}")
            if row[1] != definition["definition_hash"] or row[2] != definition.get("spec_sha256"):
                raise RuntimeError(
                    f"frozen strategy definition hash mismatch: {definition['id']}"
                )
            definition_ids[str(definition["id"])] = int(row[0])

        policy_ids: dict[str, int] = {}
        for policy in records.get("risk_policies") or []:
            cur.execute(
                """
                INSERT INTO portfolio_risk_policies (
                  external_id, version, policy_kind, max_open_symbols,
                  read_only, policy_hash, policy_json
                ) VALUES (%s, %s, %s, %s, %s, %s, CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE external_id = VALUES(external_id)
                """,
                (
                    policy["id"], policy["version"], policy["policy_kind"],
                    policy.get("max_open_symbols"), bool(policy.get("read_only")),
                    policy["policy_hash"], _json(policy.get("policy") or {}),
                ),
            )
            cur.execute(
                """
                SELECT id, policy_hash FROM portfolio_risk_policies
                WHERE external_id = %s AND version = %s
                """,
                (policy["id"], policy["version"]),
            )
            row = cur.fetchone()
            if not row or row[1] != policy["policy_hash"]:
                raise RuntimeError(f"frozen risk policy hash mismatch: {policy['id']}")
            policy_ids[str(policy["id"])] = int(row[0])

        for evidence in records.get("evidence_bundles") or []:
            cur.execute(
                """
                INSERT INTO strategy_evidence_bundles (
                  external_id, strategy_definition_id, status, admission_state,
                  bundle_hash, bundle_json
                ) VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE external_id = VALUES(external_id)
                """,
                (
                    evidence["id"], definition_ids[evidence["strategy_definition_id"]],
                    evidence["status"], evidence["admission_state"],
                    evidence.get("bundle_hash"), _json(evidence.get("bundle")),
                ),
            )

        instance_ids: dict[str, int] = {}
        for instance in records.get("instances") or []:
            cur.execute(
                """
                INSERT INTO strategy_control_instances (
                  external_id, strategy_definition_id, state, configuration_hash,
                  configuration_json, state_version, last_market_cursor, last_decision_at,
                  read_only
                ) VALUES (%s, %s, %s, %s, CAST(%s AS JSON), %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  state = VALUES(state),
                  configuration_hash = VALUES(configuration_hash),
                  configuration_json = VALUES(configuration_json),
                  state_version = VALUES(state_version),
                  last_market_cursor = VALUES(last_market_cursor),
                  last_decision_at = VALUES(last_decision_at),
                  read_only = VALUES(read_only)
                """,
                (
                    instance["id"], definition_ids[instance["strategy_definition_id"]],
                    instance["state"], instance["configuration_hash"],
                    _json(instance.get("configuration") or {}),
                    int(instance.get("state_version", 0)),
                    instance.get("last_market_cursor"), instance.get("last_decision_at"),
                    bool(instance.get("read_only")),
                ),
            )
            cur.execute(
                "SELECT id FROM strategy_control_instances WHERE external_id = %s",
                (instance["id"],),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError(f"strategy instance was not persisted: {instance['id']}")
            instance_ids[str(instance["id"])] = int(row[0])

        for binding in records.get("bindings") or []:
            cur.execute(
                "SELECT id FROM exchange_accounts WHERE external_id = %s",
                (binding["exchange_account_id"],),
            )
            account = cur.fetchone()
            if not account:
                raise RuntimeError(
                    f"binding account does not exist: {binding['exchange_account_id']}"
                )
            account_id = int(account[0])
            if binding["status"] in {"ACTIVE", "STOPPING"}:
                cur.execute(
                    """
                    SELECT external_id FROM account_strategy_bindings
                    WHERE exchange_account_id = %s
                      AND status IN ('ACTIVE', 'STOPPING')
                      AND external_id <> %s
                    FOR UPDATE
                    """,
                    (account_id, binding["id"]),
                )
                conflict = cur.fetchone()
                if conflict:
                    raise RuntimeError(
                        f"account already has an active strategy binding: {conflict[0]}"
                    )
            cur.execute(
                """
                INSERT INTO account_strategy_bindings (
                  external_id, exchange_account_id, strategy_instance_id,
                  risk_policy_id, status, stop_mode, failure_reason,
                  activated_at, deactivated_at, read_only
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  status = VALUES(status), stop_mode = VALUES(stop_mode),
                  failure_reason = VALUES(failure_reason),
                  activated_at = VALUES(activated_at),
                  deactivated_at = VALUES(deactivated_at),
                  read_only = VALUES(read_only)
                """,
                (
                    binding["id"], account_id,
                    instance_ids[binding["strategy_instance_id"]],
                    policy_ids[binding["risk_policy_id"]], binding["status"],
                    binding.get("stop_mode"), binding.get("failure_reason"),
                    binding.get("activated_at"), binding.get("deactivated_at"),
                    bool(binding.get("read_only")),
                ),
            )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
