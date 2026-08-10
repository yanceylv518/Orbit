from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Callable

from orbit.application.strategy_catalog import TB4_DEFINITION, TB4_STRATEGY_ID
from orbit.domain.strategy_control_plane import LEGACY_POLICY_KIND


TB4_LEGACY_RISK_POLICY_ID = "TB4_LIVE_SMALL_V3_LEGACY"


class StrategyControlPlaneService:
    """Administrator read model for ARCH-1 definitions, instances and bindings."""

    def __init__(self, repository: Any):
        self.repository = repository

    def overview(self) -> dict[str, Any]:
        snapshot = self.repository.snapshot().as_dict()
        return {
            "source": snapshot["source"],
            "counts": {
                key: len(snapshot[key])
                for key in (
                    "definitions", "evidence_bundles", "instances",
                    "bindings", "risk_policies", "runner_leases",
                )
            },
            "migration_state": (
                "LEGACY_PROJECTION"
                if snapshot["source"] == "LEGACY_PROJECTION"
                else "CONTROL_PLANE_READY"
            ),
        }

    def definitions(self) -> list[dict[str, Any]]:
        return self.repository.snapshot().as_dict()["definitions"]

    def evidence_bundles(self) -> list[dict[str, Any]]:
        return self.repository.snapshot().as_dict()["evidence_bundles"]

    def instances(self) -> list[dict[str, Any]]:
        return self.repository.snapshot().as_dict()["instances"]

    def bindings(self) -> list[dict[str, Any]]:
        return self.repository.snapshot().as_dict()["bindings"]

    def risk_policies(self) -> list[dict[str, Any]]:
        return self.repository.snapshot().as_dict()["risk_policies"]

    def runner_leases(self) -> list[dict[str, Any]]:
        return self.repository.snapshot().as_dict()["runner_leases"]


def legacy_tb4_control_plane_projection(
    live_pilot_control: dict[str, Any],
    live_execution_snapshot: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Project the frozen TB4 deployment without changing its execution mechanism."""

    definition = TB4_DEFINITION.as_dict()
    account_id = str(live_pilot_control.get("live_account_id") or "").strip()
    execution = live_execution_snapshot() or {}
    enabled = bool(live_pilot_control.get("auto_execution_enabled", False))
    instance_id = f"tb4-live-small:{account_id}" if account_id else ""

    definitions = [{
        "id": TB4_STRATEGY_ID,
        "family": "TREND_BASKET",
        "version": definition["version"],
        "status": "LEGACY_FROZEN",
        "implementation": definition["implementation"],
        "definition_hash": definition["definition_hash"],
        "spec_sha256": definition["spec_sha256"],
        "definition": definition,
        "read_only": True,
    }]
    evidence = [{
        "id": "TB4_LEGACY_EVIDENCE_PROJECTION",
        "strategy_definition_id": TB4_STRATEGY_ID,
        "status": "NOT_STRUCTURED",
        "admission_state": "LEGACY_BACKTEST_CONFIRMED",
        "bundle_hash": None,
        "bundle": None,
    }]
    risk_payload = {
        "execution_checklist_protocol": "LIVE_SMALL_EXECUTION_CHECKLIST_V3",
        "max_open_symbols": None,
        "compatibility_reason": (
            "TB4 is a frozen 12-market legacy basket; ARCH-1 must not retrofit "
            "the new shortline three-position rule."
        ),
    }
    risk_policies = [{
        "id": TB4_LEGACY_RISK_POLICY_ID,
        "version": "3",
        "policy_kind": LEGACY_POLICY_KIND,
        "max_open_symbols": None,
        "read_only": True,
        "policy_hash": _hash(risk_payload),
        "policy": risk_payload,
    }]
    instances: list[dict[str, Any]] = []
    bindings: list[dict[str, Any]] = []
    if account_id:
        instance_state = "RUNNING" if enabled else "STOPPED"
        config = {
            "legacy_projection": True,
            "exposure_multiplier": float(live_pilot_control.get("exposure_multiplier", 3)),
        }
        instances.append({
            "id": instance_id,
            "strategy_definition_id": TB4_STRATEGY_ID,
            "state": instance_state,
            "configuration_hash": _hash(config),
            "configuration": config,
            "state_version": 0,
            "last_market_cursor": execution.get("last_claimed_close_time_ms"),
            "last_decision_at": execution.get("updated_at"),
            "read_only": True,
        })
        bindings.append({
            "id": f"binding:{account_id}:{TB4_STRATEGY_ID}",
            "exchange_account_id": account_id,
            "strategy_instance_id": instance_id,
            "risk_policy_id": TB4_LEGACY_RISK_POLICY_ID,
            "status": "ACTIVE" if enabled else "INACTIVE",
            "stop_mode": "LEGACY_PROTOCOL",
            "failure_reason": None,
            "activated_at": None,
            "deactivated_at": None,
            "read_only": True,
        })
    return {
        "definitions": definitions,
        "evidence_bundles": evidence,
        "instances": instances,
        "bindings": bindings,
        "risk_policies": risk_policies,
        "runner_leases": [],
        "source": "LEGACY_PROJECTION",
    }


def _hash(payload: Any) -> str:
    encoded = json.dumps(
        deepcopy(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
