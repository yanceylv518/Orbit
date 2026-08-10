import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.strategy_catalog import TB4_DEFINITION, TB4_STRATEGY_ID
from orbit.application.strategy_control_plane import legacy_tb4_control_plane_projection
from orbit.domain.strategy_control_plane import (
    ControlPlaneInvariantError,
    StrategyControlPlaneSnapshot,
    validate_control_plane_snapshot,
)
from orbit.infrastructure.persistence.strategy_control_plane import (
    InMemoryStrategyControlPlaneRepository,
    MySqlStrategyControlPlaneRepository,
)
from orbit.infrastructure.persistence.strategy_control_plane_writer import (
    MySqlStrategyControlPlaneWriter,
)


class StrategyControlPlaneTests(unittest.TestCase):
    def projection(self, *, account_id="", enabled=False):
        return legacy_tb4_control_plane_projection(
            {
                "live_account_id": account_id,
                "auto_execution_enabled": enabled,
                "execution_epoch": "epoch-v3" if enabled else "",
                "exposure_multiplier": 3,
            },
            lambda: {},
        )

    def test_tb4_projection_preserves_both_frozen_hashes(self):
        records = self.projection()
        definition = records["definitions"][0]

        self.assertEqual(definition["id"], TB4_STRATEGY_ID)
        self.assertEqual(definition["definition_hash"], TB4_DEFINITION.definition_hash)
        self.assertEqual(definition["spec_sha256"], TB4_DEFINITION.spec_sha256)
        self.assertTrue(definition["read_only"])
        self.assertEqual(records["risk_policies"][0]["policy_kind"], "LEGACY_COMPATIBILITY")
        self.assertIsNone(records["risk_policies"][0]["max_open_symbols"])

    def test_live_binding_is_projected_without_changing_tb4_runtime(self):
        inactive = self.projection(account_id="account-1", enabled=False)
        active = self.projection(account_id="account-1", enabled=True)

        self.assertEqual(inactive["bindings"][0]["status"], "INACTIVE")
        self.assertEqual(active["bindings"][0]["status"], "ACTIVE")
        self.assertEqual(active["instances"][0]["state"], "RUNNING")
        self.assertTrue(active["bindings"][0]["read_only"])
        self.assertNotIn("execution_epoch", active["instances"][0]["configuration"])

    def test_shortline_policy_requires_exactly_three_open_symbols(self):
        records = self.projection()
        records["risk_policies"].append({
            "id": "shortline-v1",
            "version": "1",
            "policy_kind": "SHORTLINE_V1",
            "max_open_symbols": 4,
            "read_only": False,
        })

        with self.assertRaisesRegex(ControlPlaneInvariantError, "max_open_symbols=3"):
            InMemoryStrategyControlPlaneRepository(records)

    def test_nonlegacy_binding_cannot_bypass_shortline_policy(self):
        records = self.projection(account_id="account-1", enabled=True)
        records["definitions"][0]["status"] = "ADMITTED"

        with self.assertRaisesRegex(ControlPlaneInvariantError, "must use SHORTLINE_V1"):
            InMemoryStrategyControlPlaneRepository(records)

    def test_duplicate_active_binding_for_account_is_rejected(self):
        records = self.projection(account_id="account-1", enabled=True)
        records["bindings"].append({
            **records["bindings"][0],
            "id": "second-active-binding",
        })

        with self.assertRaisesRegex(ControlPlaneInvariantError, "more than one"):
            InMemoryStrategyControlPlaneRepository(records)

    def test_runner_lease_must_reference_exactly_one_known_instance(self):
        records = self.projection(account_id="account-1", enabled=True)
        records["runner_leases"] = [{
            "id": "lease:missing",
            "strategy_instance_id": "missing",
            "owner_id": "worker-1",
        }]

        with self.assertRaisesRegex(ControlPlaneInvariantError, "unknown instance"):
            InMemoryStrategyControlPlaneRepository(records)

        instance_id = records["instances"][0]["id"]
        records["runner_leases"] = [
            {"id": "lease:1", "strategy_instance_id": instance_id},
            {"id": "lease:2", "strategy_instance_id": instance_id},
        ]
        with self.assertRaisesRegex(ControlPlaneInvariantError, "more than one runner lease"):
            InMemoryStrategyControlPlaneRepository(records)

    def test_repository_snapshots_are_defensive_copies(self):
        repository = InMemoryStrategyControlPlaneRepository(self.projection())
        first = repository.snapshot().as_dict()
        first["definitions"][0]["status"] = "MUTATED"

        self.assertEqual(
            repository.snapshot().as_dict()["definitions"][0]["status"],
            "LEGACY_FROZEN",
        )

    def test_schema_has_additive_tables_and_database_active_binding_guard(self):
        schema = (BACKEND_ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
        for table in (
            "strategy_definitions", "strategy_evidence_bundles",
            "strategy_control_instances", "portfolio_risk_policies",
            "account_strategy_bindings", "runner_leases",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)
        self.assertIn("active_account_guard BIGINT GENERATED ALWAYS AS", schema)
        self.assertIn("uk_account_strategy_bindings_active_account", schema)
        self.assertIn("policy_kind <> 'SHORTLINE_V1' OR max_open_symbols = 3", schema)

    def test_seed_writer_is_repeatable_and_verifies_frozen_hashes(self):
        records = self.projection()
        cursor = SeedCursor(records)
        writer = MySqlStrategyControlPlaneWriter()

        writer.write(cursor, records)
        first_count = len(cursor.calls)
        writer.write(cursor, records)

        self.assertEqual(len(cursor.calls), first_count * 2)
        self.assertTrue(all(
            "ON DUPLICATE KEY UPDATE" in query
            for query, _ in cursor.calls
            if query.lstrip().startswith("INSERT")
        ))

    def test_mysql_repository_reads_and_closes_connection(self):
        records = self.projection(account_id="account-1", enabled=True)
        connection = ReadConnection(records)
        repository = MySqlStrategyControlPlaneRepository(lambda: connection)

        snapshot = repository.snapshot().as_dict()

        self.assertEqual(snapshot["source"], "MYSQL_CONTROL_PLANE")
        self.assertEqual(snapshot["definitions"][0]["id"], TB4_STRATEGY_ID)
        self.assertEqual(snapshot["bindings"][0]["exchange_account_id"], "account-1")
        self.assertTrue(connection.closed)


class SeedCursor:
    def __init__(self, records):
        self.records = records
        self.calls = []
        self._row = None

    def execute(self, query, params):
        self.calls.append((query, params))
        normalized = " ".join(query.split())
        definition = self.records["definitions"][0]
        policy = self.records["risk_policies"][0]
        if normalized.startswith("SELECT id, definition_hash, spec_sha256"):
            self._row = (1, definition["definition_hash"], definition["spec_sha256"])
        elif normalized.startswith("SELECT id, policy_hash"):
            self._row = (2, policy["policy_hash"])
        else:
            self._row = None

    def fetchone(self):
        return self._row


class ReadConnection:
    def __init__(self, records):
        self.records = records
        self.closed = False

    def cursor(self):
        return ReadCursor(self.records)

    def close(self):
        self.closed = True


class ReadCursor:
    def __init__(self, records):
        self.records = records
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, query):
        normalized = " ".join(query.split())
        now = datetime(2026, 8, 10, tzinfo=timezone.utc)
        if "FROM strategy_definitions" in normalized:
            self.rows = [tuple([
                item["id"], item["family"], item["version"], item["status"],
                item["implementation"], item["definition_hash"], item["spec_sha256"],
                json.dumps(item["definition"]), item["read_only"], now,
            ]) for item in self.records["definitions"]]
        elif "FROM strategy_evidence_bundles" in normalized:
            self.rows = [tuple([
                item["id"], item["strategy_definition_id"], item["status"],
                item["admission_state"], item["bundle_hash"],
                json.dumps(item["bundle"]), now,
            ]) for item in self.records["evidence_bundles"]]
        elif "FROM strategy_control_instances" in normalized:
            self.rows = [tuple([
                item["id"], item["strategy_definition_id"], item["state"],
                item["configuration_hash"], json.dumps(item["configuration"]),
                item["state_version"], item["last_market_cursor"], None,
                item["read_only"], now, now,
            ]) for item in self.records["instances"]]
        elif "FROM account_strategy_bindings" in normalized:
            self.rows = [tuple([
                item["id"], item["exchange_account_id"],
                item["strategy_instance_id"], item["risk_policy_id"],
                item["status"], item["stop_mode"], item["failure_reason"], None, None,
                item["read_only"],
            ]) for item in self.records["bindings"]]
        elif "FROM portfolio_risk_policies" in normalized:
            self.rows = [tuple([
                item["id"], item["version"], item["policy_kind"],
                item["max_open_symbols"], item["read_only"], item["policy_hash"],
                json.dumps(item["policy"]), now,
            ]) for item in self.records["risk_policies"]]
        elif "FROM runner_leases" in normalized:
            self.rows = []
        else:
            raise AssertionError(f"unexpected query: {normalized}")

    def fetchall(self):
        return self.rows


if __name__ == "__main__":
    unittest.main()
