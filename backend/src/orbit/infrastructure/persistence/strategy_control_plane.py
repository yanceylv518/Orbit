from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from orbit.domain.strategy_control_plane import (
    StrategyControlPlaneSnapshot,
    validate_control_plane_snapshot,
)


class InMemoryStrategyControlPlaneRepository:
    def __init__(self, records: dict[str, Any]):
        self._snapshot = snapshot_from_records(records)

    def snapshot(self) -> StrategyControlPlaneSnapshot:
        return snapshot_from_records(self._snapshot.as_dict())


class MySqlStrategyControlPlaneRepository:
    """Read-only adapter for the additive ARCH-1 control-plane tables."""

    def __init__(self, connection_factory: Callable[..., Any]):
        self._connection_factory = connection_factory

    def snapshot(self) -> StrategyControlPlaneSnapshot:
        conn = self._connection_factory()
        try:
            with conn.cursor() as cur:
                records = {
                    "definitions": self._definitions(cur),
                    "evidence_bundles": self._evidence(cur),
                    "instances": self._instances(cur),
                    "bindings": self._bindings(cur),
                    "risk_policies": self._risk_policies(cur),
                    "runner_leases": self._leases(cur),
                    "source": "MYSQL_CONTROL_PLANE",
                }
            return snapshot_from_records(records)
        finally:
            conn.close()

    @staticmethod
    def _definitions(cur: Any) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT external_id, family, version, status, implementation,
                   definition_hash, spec_sha256, definition_json, read_only, created_at
            FROM strategy_definitions ORDER BY external_id, version
            """
        )
        return [
            {
                "id": row[0], "family": row[1], "version": row[2],
                "status": row[3], "implementation": row[4],
                "definition_hash": row[5], "spec_sha256": row[6],
                "definition": _json_value(row[7]), "read_only": bool(row[8]),
                "created_at": _iso(row[9]),
            }
            for row in cur.fetchall()
        ]

    @staticmethod
    def _evidence(cur: Any) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT eb.external_id, sd.external_id, eb.status, eb.admission_state,
                   eb.bundle_hash, eb.bundle_json, eb.created_at
            FROM strategy_evidence_bundles eb
            JOIN strategy_definitions sd ON sd.id = eb.strategy_definition_id
            ORDER BY eb.id
            """
        )
        return [
            {
                "id": row[0], "strategy_definition_id": row[1],
                "status": row[2], "admission_state": row[3],
                "bundle_hash": row[4], "bundle": _json_value(row[5]),
                "created_at": _iso(row[6]),
            }
            for row in cur.fetchall()
        ]

    @staticmethod
    def _instances(cur: Any) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT si.external_id, sd.external_id, si.state, si.configuration_hash,
                   si.configuration_json, si.state_version, si.last_market_cursor,
                   si.last_decision_at, si.read_only, si.created_at, si.updated_at
            FROM strategy_control_instances si
            JOIN strategy_definitions sd ON sd.id = si.strategy_definition_id
            ORDER BY si.id
            """
        )
        return [
            {
                "id": row[0], "strategy_definition_id": row[1], "state": row[2],
                "configuration_hash": row[3], "configuration": _json_value(row[4]),
                "state_version": int(row[5]), "last_market_cursor": row[6],
                "last_decision_at": _iso(row[7]), "read_only": bool(row[8]),
                "created_at": _iso(row[9]), "updated_at": _iso(row[10]),
            }
            for row in cur.fetchall()
        ]

    @staticmethod
    def _bindings(cur: Any) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT b.external_id, ea.external_id, si.external_id, rp.external_id,
                   b.status, b.stop_mode, b.failure_reason,
                   b.activated_at, b.deactivated_at, b.read_only
            FROM account_strategy_bindings b
            JOIN exchange_accounts ea ON ea.id = b.exchange_account_id
            JOIN strategy_control_instances si ON si.id = b.strategy_instance_id
            JOIN portfolio_risk_policies rp ON rp.id = b.risk_policy_id
            ORDER BY b.id
            """
        )
        return [
            {
                "id": row[0], "exchange_account_id": row[1],
                "strategy_instance_id": row[2], "risk_policy_id": row[3],
                "status": row[4], "stop_mode": row[5], "failure_reason": row[6],
                "activated_at": _iso(row[7]), "deactivated_at": _iso(row[8]),
                "read_only": bool(row[9]),
            }
            for row in cur.fetchall()
        ]

    @staticmethod
    def _risk_policies(cur: Any) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT external_id, version, policy_kind, max_open_symbols,
                   read_only, policy_hash, policy_json, created_at
            FROM portfolio_risk_policies ORDER BY external_id, version
            """
        )
        return [
            {
                "id": row[0], "version": row[1], "policy_kind": row[2],
                "max_open_symbols": row[3], "read_only": bool(row[4]),
                "policy_hash": row[5], "policy": _json_value(row[6]),
                "created_at": _iso(row[7]),
            }
            for row in cur.fetchall()
        ]

    @staticmethod
    def _leases(cur: Any) -> list[dict[str, Any]]:
        cur.execute(
            """
            SELECT si.external_id, rl.owner_id, rl.fencing_token,
                   rl.lease_until, rl.heartbeat_at
            FROM runner_leases rl
            JOIN strategy_control_instances si ON si.id = rl.strategy_instance_id
            ORDER BY rl.strategy_instance_id
            """
        )
        return [
            {
                "id": f"lease:{row[0]}", "strategy_instance_id": row[0],
                "owner_id": row[1], "fencing_token": int(row[2]),
                "lease_until": _iso(row[3]), "heartbeat_at": _iso(row[4]),
            }
            for row in cur.fetchall()
        ]


def snapshot_from_records(records: dict[str, Any]) -> StrategyControlPlaneSnapshot:
    snapshot = StrategyControlPlaneSnapshot(
        definitions=tuple(deepcopy(records.get("definitions") or [])),
        evidence_bundles=tuple(deepcopy(records.get("evidence_bundles") or [])),
        instances=tuple(deepcopy(records.get("instances") or [])),
        bindings=tuple(deepcopy(records.get("bindings") or [])),
        risk_policies=tuple(deepcopy(records.get("risk_policies") or [])),
        runner_leases=tuple(deepcopy(records.get("runner_leases") or [])),
        source=str(records.get("source") or "IN_MEMORY"),
    )
    validate_control_plane_snapshot(snapshot)
    return snapshot


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        import json
        return json.loads(value)
    return deepcopy(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
