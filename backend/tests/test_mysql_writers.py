import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.persistence.mysql_audit_writer import MySqlAuditWriter
from orbit.infrastructure.persistence.mysql_event_writer import MySqlEventHistoryWriter
from orbit.infrastructure.persistence.mysql_report_writer import MySqlReportWriter
from orbit.infrastructure.persistence.mysql_config_writer import MySqlConfigWriter
from orbit.infrastructure.persistence.mysql_market_snapshot_writer import MySqlMarketSnapshotWriter
from orbit.infrastructure.persistence.mysql_symbol_state_writer import MySqlSymbolStateWriter
from orbit.config import load_config


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))

    def fetchone(self):
        return (len(self.calls),)


class MySqlWriterTest(unittest.TestCase):
    def setUp(self):
        self.strategy = {
            "id": "strategy_001",
            "user_id": "user_001",
            "exchange_account_id": "acc_001",
        }
        self.ids = {
            "strategy:strategy_001": 3,
            "user:user_001": 1,
            "user:admin_001": 2,
            "account:acc_001": 4,
        }

    def test_event_writer_writes_strategy_and_trade_events(self):
        cursor = RecordingCursor()
        payload = {
            "strategy_instance": self.strategy,
            "strategy_events": [{
                "id": "event_001", "timestamp": "2026-07-10T00:00:00+00:00",
                "symbol": "BTCUSDT", "event_type": "PROFIT_TRANSFER", "trades": [],
            }],
            "trade_events": [{
                "id": "trade_001", "strategy_event_id": "event_001",
                "timestamp": "2026-07-10T00:00:00+00:00", "symbol": "BTCUSDT",
                "event_type": "PROFIT_TRANSFER", "side": "SELL", "position_side": "LONG",
                "action": "REDUCE", "price": 1, "fill_price": 1, "qty": 1, "notional": 1,
            }],
        }

        MySqlEventHistoryWriter().write(cursor, payload, self.ids)

        self.assertEqual(len(cursor.calls), 2)
        self.assertIn("strategy_events", cursor.calls[0][0])
        self.assertIn("trade_events", cursor.calls[1][0])

    def test_audit_writer_skips_unknown_actor_and_writes_known_actor(self):
        cursor = RecordingCursor()
        payload = {"admin_audit_logs": [
            {"id": "skip", "admin_user_id": "missing"},
            {
                "id": "audit_001", "admin_user_id": "admin_001", "action_type": "TEST",
                "timestamp": "2026-07-10T00:00:00+00:00",
            },
        ]}

        MySqlAuditWriter().write(cursor, payload, self.ids)

        self.assertEqual(len(cursor.calls), 1)
        self.assertIn("admin_audit_logs", cursor.calls[0][0])

    def test_report_writer_upserts_daily_report(self):
        cursor = RecordingCursor()
        payload = {
            "strategy_instance": self.strategy,
            "daily_reports": [{"id": "report_001", "date": "2026-07-10"}],
        }

        MySqlReportWriter().write(cursor, payload, self.ids)

        self.assertEqual(len(cursor.calls), 1)
        self.assertIn("daily_reports", cursor.calls[0][0])
        self.assertIn("ON DUPLICATE KEY UPDATE", cursor.calls[0][0])

    def test_config_writer_returns_database_ids(self):
        cursor = RecordingCursor()
        config = load_config(str(ROOT / "config" / "config.sample.json"))
        payload = {
            "users": config["users"],
            "exchange_accounts": config["exchange_accounts"],
            "strategy_instance": config["strategy_instances"][0],
        }

        ids = MySqlConfigWriter().write(cursor, payload)

        self.assertIn(f"strategy:{payload['strategy_instance']['id']}", ids)
        self.assertTrue(any("exchange_accounts" in query for query, _ in cursor.calls))

    def test_symbol_and_market_writers_use_resolved_strategy_ids(self):
        cursor = RecordingCursor()
        symbol_payload = {
            "strategy_instance": self.strategy,
            "symbol_states": {"BTCUSDT": {"state": "BALANCED", "base_price": 60000}},
        }
        market_payload = {
            "strategy_instance": self.strategy,
            "symbol_views": {"BTCUSDT": {
                "price": 60000, "state": "BALANCED", "long_qty": 1, "short_qty": 1,
                "long_unrealized_pnl": 0, "short_unrealized_pnl": 0, "realized_pnl": 0,
                "net_exposure": 0, "gross_exposure": 120000, "equity": 100,
            }},
        }

        MySqlSymbolStateWriter().write(cursor, symbol_payload, self.ids)
        MySqlMarketSnapshotWriter().write(cursor, market_payload, self.ids)

        self.assertTrue(any("symbol_states" in query for query, _ in cursor.calls))
        self.assertTrue(any("market_snapshots" in query for query, _ in cursor.calls))


if __name__ == "__main__":
    unittest.main()
