from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.live_reconciliation import LiveReconciliationService
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC
from orbit.infrastructure.persistence.account_snapshots import InMemoryAccountSnapshotRepository
from orbit.infrastructure.persistence.live_equity_ledger import AppendOnlyLiveEquityLedger


def checklist():
    rows = []
    targets = {
        "BTCUSDT": ("LONG", 0.01, "EXECUTABLE"),
        "ETHUSDT": ("SHORT", -0.02, "EXECUTABLE"),
        "BNBUSDT": ("LONG", 0.0, "BELOW_MIN_NOTIONAL"),
        "XRPUSDT": ("SHORT", -10.0, "EXECUTABLE"),
    }
    for symbol in TB4_SPEC.symbols:
        direction, quantity, status = targets.get(symbol, ("FLAT", 0.0, "FLAT"))
        rows.append({
            "symbol": symbol,
            "direction": direction,
            "signed_target_quantity": quantity,
            "quantity_step": "0.001",
            "status": status,
        })
    return {
        "status": "READY",
        "close_time_ms": 10,
        "rebalance_time_ms": 8,
        "rows": rows,
        "summary": {"executable_notional_ratio": 0.75},
    }


class TrendSnapshot:
    def __init__(self):
        self.paper_equity = 1.0

    def __call__(self):
        return {
            "runner": {"equity": self.paper_equity},
            "execution_checklist": checklist(),
        }


class LiveReconciliationServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "equity.jsonl"
        self.account_id = "live_001"
        self.trend = TrendSnapshot()
        self.snapshot = {
            "status": "synced",
            "account_id": self.account_id,
            "testnet": False,
            "dry_run": False,
            "synced_at": 1_000,
            "total_margin_balance": 500.0,
            "positions": [
                {
                    "symbol": "BTCUSDT",
                    "position_side": "LONG",
                    "position_amt": 0.0105,
                },
                {
                    "symbol": "ETHUSDT",
                    "position_side": "SHORT",
                    "position_amt": -0.018,
                },
                {
                    "symbol": "XRPUSDT",
                    "position_side": "LONG",
                    "position_amt": 10,
                },
                {
                    "symbol": "UNIUSDT",
                    "position_side": "BOTH",
                    "position_amt": 0.5,
                },
            ],
        }
        self.snapshots = InMemoryAccountSnapshotRepository({
            self.account_id: self.snapshot,
        })
        self.ledger = AppendOnlyLiveEquityLedger(self.path)
        self.service = LiveReconciliationService(
            live_account_id=self.account_id,
            account_snapshots=self.snapshots,
            trend_forward_snapshot=self.trend,
            equity_ledger=self.ledger,
            quantity_tolerance_pct=1.0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_position_reconciliation_covers_all_four_states_without_mutation(self):
        before = deepcopy(self.snapshot)

        result = self.service.snapshot()

        rows = {row["symbol"]: row for row in result["positions"]["rows"]}
        self.assertEqual(rows["BTCUSDT"]["status"], "MATCH")
        self.assertEqual(rows["ETHUSDT"]["status"], "DEVIATION")
        self.assertEqual(rows["BNBUSDT"]["status"], "EXPECTED_FLAT")
        self.assertEqual(rows["XRPUSDT"]["status"], "DEVIATION")
        self.assertEqual(rows["UNIUSDT"]["status"], "UNEXPECTED_POSITION")
        self.assertFalse(rows["XRPUSDT"]["direction_match"])
        self.assertEqual(result["positions"]["deviation_count"], 3)
        self.assertEqual(self.snapshot, before)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["auto_correction"])

    def test_tolerance_boundary_is_inclusive(self):
        self.snapshot["positions"][0]["position_amt"] = 0.0111

        result = self.service.snapshot()

        btc = next(
            row for row in result["positions"]["rows"]
            if row["symbol"] == "BTCUSDT"
        )
        self.assertEqual(btc["tolerance_quantity"], 0.0011)
        self.assertEqual(btc["status"], "MATCH")

    def test_equity_observations_are_append_only_and_normalized_to_first_sync(self):
        first = self.service.record_snapshot(self.account_id, self.snapshot)
        duplicate = self.service.record_snapshot(self.account_id, self.snapshot)
        self.snapshot["synced_at"] = int(
            datetime(2026, 1, 8, tzinfo=timezone.utc).timestamp() * 1000
        )
        self.snapshot["total_margin_balance"] = 525.0
        self.trend.paper_equity = 1.1
        second = self.service.record_snapshot(self.account_id, self.snapshot)

        result = self.service.snapshot()["equity"]

        self.assertTrue(first["recorded"])
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(second["recorded"])
        self.assertEqual(len(result["points"]), 2)
        self.assertAlmostEqual(result["points"][-1]["live_normalized"], 1.05)
        self.assertAlmostEqual(result["points"][-1]["paper_normalized"], 1.1)
        self.assertAlmostEqual(result["cumulative_deviation_pct"], -5.0)
        self.assertEqual(len(result["weekly_points"]), 2)
        self.assertAlmostEqual(result["latest_weekly_deviation_pct"], -5.0)
        self.assertEqual(result["structural_tracking_ratio"], 0.75)

    def test_recording_is_blocked_for_non_live_or_unconfigured_account(self):
        unconfigured = LiveReconciliationService(
            live_account_id="",
            account_snapshots=self.snapshots,
            trend_forward_snapshot=self.trend,
            equity_ledger=self.ledger,
        )
        self.assertEqual(
            unconfigured.record_snapshot(self.account_id, self.snapshot)["reason"],
            "ACCOUNT_NOT_CONFIGURED",
        )
        self.snapshot["testnet"] = True
        self.assertEqual(
            self.service.record_snapshot(self.account_id, self.snapshot)["reason"],
            "ACCOUNT_NOT_LIVE",
        )
        self.assertEqual(self.ledger.status()["event_count"], 0)

    def test_hash_chain_detects_tampered_equity_observation(self):
        self.service.record_snapshot(self.account_id, self.snapshot)
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["payload"]["live_equity_usdt"] = 999
        self.path.write_text(
            json.dumps(record, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
            self.ledger.read_all()
        self.assertEqual(self.service.snapshot()["status"], "DATA_INTEGRITY_ERROR")

    def test_invalid_paper_equity_and_timestamp_do_not_raise_from_sync_hook(self):
        self.trend.paper_equity = 0
        self.assertEqual(
            self.service.record_snapshot(self.account_id, self.snapshot)["reason"],
            "INVALID_PAPER_EQUITY",
        )
        self.trend.paper_equity = 1
        self.snapshot["synced_at"] = None
        result = self.service.record_snapshot(self.account_id, self.snapshot)
        self.assertEqual(result["reason"], "LEDGER_ERROR")
        self.assertEqual(self.ledger.status()["event_count"], 0)


if __name__ == "__main__":
    unittest.main()
