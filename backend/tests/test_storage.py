import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.persistence.storage import MySqlStateStore


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params):
        return None


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self):
        return FakeCursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class FakeWriter:
    def __init__(self, *, fail=False):
        self.fail = fail

    def write(self, cursor, payload, ids):
        if self.fail:
            raise RuntimeError("audit write failed")


class FakeConfigWriter:
    def write(self, cursor, payload):
        return {}


class MySqlStateStoreTransactionTest(unittest.TestCase):
    def make_store(self, connection, *, fail=False):
        store = MySqlStateStore.__new__(MySqlStateStore)

        def connect(*, autocommit=True):
            self.assertFalse(autocommit)
            return connection

        store._connect = connect
        store._ensure_runtime_schema = lambda: None
        store.config_writer = FakeConfigWriter()
        store.symbol_state_writer = FakeWriter()
        store.market_snapshot_writer = FakeWriter()
        store.event_history_writer = FakeWriter()
        store.audit_writer = FakeWriter(fail=fail)
        store.report_writer = FakeWriter()
        return store

    def test_save_commits_all_runtime_writes_once(self):
        connection = FakeConnection()
        store = self.make_store(connection)

        store.save({})

        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)

    def test_save_rolls_back_when_a_runtime_write_fails(self):
        connection = FakeConnection()
        store = self.make_store(connection, fail=True)

        with self.assertRaises(RuntimeError):
            store.save({})

        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertTrue(connection.closed)

    def test_directory_load_migrates_runtime_schema_before_querying(self):
        calls = []
        connection = FakeConnection()
        store = MySqlStateStore.__new__(MySqlStateStore)
        store._ensure_runtime_schema = lambda: calls.append("migrate")
        store._connect = lambda: calls.append("connect") or connection
        store.ensure_identity_schema = lambda: calls.append("identity")
        store._load_users = lambda cursor: []
        store._load_accounts = lambda cursor: []
        store._load_strategies = lambda cursor: []
        store._load_run_configs = lambda cursor: calls.append("query") or []

        directory = store.load_directory()

        self.assertEqual(calls, ["migrate", "connect", "identity", "query"])
        self.assertEqual(directory["account_run_configs"], [])
        self.assertTrue(connection.closed)

    def test_symbol_state_index_replacement_is_added_before_legacy_drop(self):
        cursor = IndexMigrationCursor()
        store = MySqlStateStore.__new__(MySqlStateStore)
        store._ensure_column = lambda *args: None

        store._ensure_symbol_state_account_key(cursor)

        alterations = [query for query, _ in cursor.calls if query.startswith("ALTER TABLE")]
        self.assertIn("ADD UNIQUE KEY", alterations[0])
        self.assertIn("DROP INDEX", alterations[1])

    def test_control_plane_repository_is_live_mysql_adapter_when_seeded(self):
        connection = ControlPlaneProbeConnection(table_exists=True, definition_count=1)
        store = MySqlStateStore.__new__(MySqlStateStore)
        store._connect = lambda: connection

        repository = store.strategy_control_plane_repository()

        self.assertIsNotNone(repository)
        self.assertEqual(repository.__class__.__name__, "MySqlStrategyControlPlaneRepository")
        self.assertTrue(connection.closed)

    def test_control_plane_repository_is_absent_before_migration(self):
        connection = ControlPlaneProbeConnection(table_exists=False, definition_count=0)
        store = MySqlStateStore.__new__(MySqlStateStore)
        store._connect = lambda: connection

        self.assertIsNone(store.strategy_control_plane_repository())
        self.assertTrue(connection.closed)


class ControlPlaneProbeConnection:
    def __init__(self, *, table_exists, definition_count):
        self.cursor_instance = ControlPlaneProbeCursor(
            table_exists=table_exists,
            definition_count=definition_count,
        )
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


class ControlPlaneProbeCursor:
    def __init__(self, *, table_exists, definition_count):
        self.table_exists = table_exists
        self.definition_count = definition_count
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        if normalized.startswith("SHOW TABLES LIKE"):
            self.row = ("strategy_definitions",) if self.table_exists else None
        elif normalized.startswith("SELECT COUNT(*)"):
            self.row = (self.definition_count,)
        else:
            raise AssertionError(f"unexpected query: {normalized}")

    def fetchone(self):
        return self.row


class IndexMigrationCursor:
    def __init__(self):
        self.calls = []
        self.row = None

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.calls.append((normalized, params))
        if normalized.startswith("SHOW INDEX"):
            self.row = None if params[0].endswith("account_symbol") else ("legacy",)
        else:
            self.row = None

    def fetchone(self):
        return self.row


if __name__ == "__main__":
    unittest.main()
