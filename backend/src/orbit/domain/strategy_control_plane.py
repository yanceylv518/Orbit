from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable


ACTIVE_BINDING_STATUSES = frozenset({"ACTIVE", "STOPPING"})
SHORTLINE_POLICY_KIND = "SHORTLINE_V1"
LEGACY_POLICY_KIND = "LEGACY_COMPATIBILITY"


class ControlPlaneInvariantError(ValueError):
    pass


@dataclass(frozen=True)
class StrategyControlPlaneSnapshot:
    definitions: tuple[dict[str, Any], ...]
    evidence_bundles: tuple[dict[str, Any], ...]
    instances: tuple[dict[str, Any], ...]
    bindings: tuple[dict[str, Any], ...]
    risk_policies: tuple[dict[str, Any], ...]
    runner_leases: tuple[dict[str, Any], ...]
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "definitions": deepcopy(list(self.definitions)),
            "evidence_bundles": deepcopy(list(self.evidence_bundles)),
            "instances": deepcopy(list(self.instances)),
            "bindings": deepcopy(list(self.bindings)),
            "risk_policies": deepcopy(list(self.risk_policies)),
            "runner_leases": deepcopy(list(self.runner_leases)),
            "source": self.source,
        }


def validate_control_plane_snapshot(snapshot: StrategyControlPlaneSnapshot) -> None:
    definition_ids = _unique_ids(snapshot.definitions, "strategy definition")
    instance_ids = _unique_ids(snapshot.instances, "strategy instance")
    risk_policy_ids = _unique_ids(snapshot.risk_policies, "risk policy")
    _unique_ids(snapshot.bindings, "account strategy binding")
    _unique_ids(snapshot.evidence_bundles, "strategy evidence bundle")
    _unique_ids(snapshot.runner_leases, "runner lease")
    definitions_by_id = {
        str(item["id"]): item for item in snapshot.definitions
    }
    instances_by_id = {
        str(item["id"]): item for item in snapshot.instances
    }
    policies_by_id = {
        str(item["id"]): item for item in snapshot.risk_policies
    }

    for instance in snapshot.instances:
        if str(instance.get("strategy_definition_id") or "") not in definition_ids:
            raise ControlPlaneInvariantError(
                f"strategy instance {instance.get('id')} references an unknown definition"
            )
    for bundle in snapshot.evidence_bundles:
        if str(bundle.get("strategy_definition_id") or "") not in definition_ids:
            raise ControlPlaneInvariantError(
                f"evidence bundle {bundle.get('id')} references an unknown definition"
            )

    leased_instances: set[str] = set()
    for lease in snapshot.runner_leases:
        instance_id = str(lease.get("strategy_instance_id") or "")
        if instance_id not in instance_ids:
            raise ControlPlaneInvariantError(
                f"runner lease {lease.get('id')} references an unknown instance"
            )
        if instance_id in leased_instances:
            raise ControlPlaneInvariantError(
                f"strategy instance {instance_id} has more than one runner lease"
            )
        leased_instances.add(instance_id)

    active_accounts: dict[str, str] = {}
    for binding in snapshot.bindings:
        instance_id = str(binding.get("strategy_instance_id") or "")
        if instance_id not in instance_ids:
            raise ControlPlaneInvariantError(
                f"binding {binding.get('id')} references an unknown instance"
            )
        policy_id = str(binding.get("risk_policy_id") or "")
        if policy_id not in risk_policy_ids:
            raise ControlPlaneInvariantError(
                f"binding {binding.get('id')} references an unknown risk policy"
            )
        definition = definitions_by_id[
            str(instances_by_id[instance_id]["strategy_definition_id"])
        ]
        policy_kind = str(policies_by_id[policy_id].get("policy_kind") or "")
        legacy_definition = str(definition.get("status") or "") == "LEGACY_FROZEN"
        required_policy = LEGACY_POLICY_KIND if legacy_definition else SHORTLINE_POLICY_KIND
        if policy_kind != required_policy:
            raise ControlPlaneInvariantError(
                f"binding {binding.get('id')} must use {required_policy} risk policy"
            )
        status = str(binding.get("status") or "").upper()
        account_id = str(binding.get("exchange_account_id") or "")
        if status in ACTIVE_BINDING_STATUSES:
            previous = active_accounts.setdefault(account_id, str(binding.get("id")))
            if previous != str(binding.get("id")):
                raise ControlPlaneInvariantError(
                    f"account {account_id} has more than one active or stopping binding"
                )

    for policy in snapshot.risk_policies:
        kind = str(policy.get("policy_kind") or "")
        if kind not in {SHORTLINE_POLICY_KIND, LEGACY_POLICY_KIND}:
            raise ControlPlaneInvariantError(f"unsupported risk policy kind: {kind}")
        maximum = policy.get("max_open_symbols")
        if kind == SHORTLINE_POLICY_KIND and int(maximum or 0) != 3:
            raise ControlPlaneInvariantError(
                "new shortline risk policies must enforce max_open_symbols=3"
            )
        if kind == LEGACY_POLICY_KIND and not bool(policy.get("read_only")):
            raise ControlPlaneInvariantError(
                "legacy compatibility policies must be read-only"
            )


def _unique_ids(items: Iterable[dict[str, Any]], label: str) -> set[str]:
    identifiers: set[str] = set()
    for item in items:
        identifier = str(item.get("id") or "").strip()
        if not identifier:
            raise ControlPlaneInvariantError(f"{label} id is required")
        if identifier in identifiers:
            raise ControlPlaneInvariantError(f"duplicate {label} id: {identifier}")
        identifiers.add(identifier)
    return identifiers
