from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.live_execution import LiveExecutionService
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC
from orbit.infrastructure.persistence.live_execution_ledger import (
    AppendOnlyLiveExecutionLedger,
)


NOW = int(datetime(2026, 7, 30, tzinfo=timezone.utc).timestamp() * 1000)


class Accounts:
    def __init__(self, account=None):
        self.account = account or {
            "id": "live_001",
            "status": "active",
            "testnet": False,
            "dry_run": False,
        }

    def account_by_id(self, account_id):
        return self.account if account_id == self.account["id"] else None


class Equity:
    def __init__(self, observations=None):
        self.rows = observations or [
            {"live_equity_usdt": 500, "paper_equity": 1.0},
        ]

    def observations(self, _account_id):
        return deepcopy(self.rows)


class Gateway:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.orders = []

    def place_order(self, params):
        self.orders.append(deepcopy(params))
        outcome = self.outcomes.get(params["symbol"], {})
        if isinstance(outcome, Exception):
            raise outcome
        return {
            "orderId": len(self.orders),
            "executedQty": outcome.get("executedQty", params["quantity"]),
            "avgPrice": outcome.get("avgPrice", "10.1"),
            "status": outcome.get("status", "FILLED"),
        }

    def user_trades(self, symbol, order_id):
        outcome = self.outcomes.get(symbol, {})
        if isinstance(outcome, Exception):
            return []
        if outcome.get("tradeError"):
            raise RuntimeError(outcome["tradeError"])
        qty = outcome.get("tradeQty", outcome.get("executedQty", "1"))
        return [] if qty == "0" else [{
            "orderId": order_id,
            "qty": qty,
            "price": outcome.get("avgPrice", "10.1"),
            "commission": outcome.get("commission", "0.004"),
            "commissionAsset": "USDT",
        }]


def checklist(*, stale=False, targets=None, rebalance=123_000):
    targets = targets or {"BTCUSDT": 1.0}
    rows = []
    for symbol in TB4_SPEC.symbols:
        target = float(targets.get(symbol, 0))
        rows.append({
            "symbol": symbol,
            "signed_target_quantity": target,
            "quantity_step": "0.1",
            "min_quantity": "0.1",
            "min_notional_usdt": 5,
            "close_price": 10,
            "status": "EXECUTABLE" if target else "FLAT",
        })
    gross = sum(abs(value) * 10 for value in targets.values())
    return {
        "protocol": "LIVE_SMALL_EXECUTION_CHECKLIST_V1",
        "status": "READY",
        "rules_stale": stale,
        "rebalance_time_ms": rebalance,
        "rows": rows,
        "summary": {"target_gross_notional_usdt": gross},
    }


def account_snapshot(*, dual=False, positions=None):
    return {
        "status": "synced",
        "account_id": "live_001",
        "testnet": False,
        "dry_run": False,
        "synced_at": NOW,
        "position_mode": {"dual_side_position": dual},
        "positions": positions or [],
    }


class LiveExecutionServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "executions.jsonl"
        self.ledger = AppendOnlyLiveExecutionLedger(self.path)
        self.gateway = Gateway()
        self.current_checklist = checklist()
        self.sync_calls = 0
        self.snapshot = account_snapshot()

    def tearDown(self):
        self.tmp.cleanup()

    def service(self, **overrides):
        values = {
            "enabled": True,
            "execution_epoch": "pilot-001",
            "live_account_id": "live_001",
            "accounts": Accounts(),
            "account_snapshots": object(),
            "trend_forward_snapshot": lambda: {
                "execution_checklist": deepcopy(self.current_checklist),
            },
            "gateway_factory": lambda _account: self.gateway,
            "execution_ledger": self.ledger,
            "equity_ledger": Equity(),
            "reconciliation_snapshot": lambda: {
                "status": "READY",
                "positions": {"status": "MATCH", "rows": []},
            },
            "max_snapshot_age_seconds": 120,
            "max_order_notional_usdt": 150,
            "round_gross_multiplier": 1.1,
            "now_ms": lambda: NOW,
        }
        values.update(overrides)
        return LiveExecutionService(**values)

    def sync(self, _account_id):
        self.sync_calls += 1
        return deepcopy(self.snapshot)

    def test_default_disabled_performs_no_sync_or_order(self):
        service = self.service(enabled=False)

        result = service.execute_due(self.sync)

        self.assertEqual(result["status"], "DISABLED")
        self.assertEqual(self.sync_calls, 0)
        self.assertEqual(self.gateway.orders, [])
        self.assertEqual(self.ledger.status()["event_count"], 0)

    def test_each_enablement_gate_rejects_before_order(self):
        cases = [
            ("execution_epoch", "", "EXECUTION_EPOCH_NOT_CONFIGURED"),
            ("live_account_id", "", "LIVE_ACCOUNT_NOT_CONFIGURED"),
            ("accounts", Accounts({"id": "live_001", "status": "active", "testnet": True, "dry_run": False}), "TESTNET_ACCOUNT_REJECTED"),
            ("accounts", Accounts({"id": "live_001", "status": "active", "testnet": False, "dry_run": True}), "DRY_RUN_ACCOUNT_REJECTED"),
        ]
        for index, (field, value, expected) in enumerate(cases):
            with self.subTest(expected):
                ledger = AppendOnlyLiveExecutionLedger(
                    Path(self.tmp.name) / f"gate-{index}.jsonl"
                )
                result = self.service(
                    execution_ledger=ledger, **{field: value},
                ).execute_due(self.sync)
                self.assertEqual(result["reason"], expected)
        stale_ledger = AppendOnlyLiveExecutionLedger(Path(self.tmp.name) / "stale.jsonl")
        self.current_checklist["rules_stale"] = True
        result = self.service(execution_ledger=stale_ledger).execute_due(self.sync)
        self.assertEqual(result["reason"], "EXCHANGE_RULES_STALE")
        self.current_checklist["rules_stale"] = False
        dual_ledger = AppendOnlyLiveExecutionLedger(Path(self.tmp.name) / "dual.jsonl")
        self.snapshot = account_snapshot(dual=True)
        result = self.service(execution_ledger=dual_ledger).execute_due(self.sync)
        self.assertEqual(result["reason"], "HEDGE_MODE_REJECTED")
        self.snapshot = account_snapshot()
        self.snapshot["synced_at"] = NOW - 121_000
        stale_snapshot_ledger = AppendOnlyLiveExecutionLedger(
            Path(self.tmp.name) / "stale-snapshot.jsonl"
        )
        result = self.service(
            execution_ledger=stale_snapshot_ledger,
        ).execute_due(self.sync)
        self.assertEqual(result["reason"], "ACCOUNT_SNAPSHOT_STALE")
        self.snapshot = account_snapshot()
        self.current_checklist["status"] = "AWAITING_FIRST_REBALANCE"
        not_ready_ledger = AppendOnlyLiveExecutionLedger(
            Path(self.tmp.name) / "not-ready.jsonl"
        )
        result = self.service(
            execution_ledger=not_ready_ledger,
        ).execute_due(self.sync)
        self.assertEqual(result["reason"], "CHECKLIST_NOT_READY")
        self.assertEqual(self.gateway.orders, [])

    def test_executes_once_maps_order_and_calculates_slippage_fee(self):
        service = self.service()

        first = service.execute_due(self.sync)
        second = service.execute_due(self.sync)

        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(second["status"], "ALREADY_CONSUMED")
        self.assertEqual(len(self.gateway.orders), 1)
        row = first["report"]["rows"][-1]
        self.assertEqual(row["symbol"], "BTCUSDT")
        self.assertEqual(row["status"], "EXECUTED_MATCH")
        self.assertAlmostEqual(row["slippage_bps"], 100.0)
        self.assertEqual(row["fee"], 0.004)
        order_event = next(
            item["payload"] for item in self.ledger.read_all()
            if item["payload"]["event_type"] == "ORDER_RESULT"
        )
        self.assertEqual(
            order_event["order_intent"]["source"],
            "FROZEN_TB4_CHECKLIST",
        )
        self.assertTrue(order_event["checklist_row_sha256"])

    def test_partial_failure_dust_and_below_min_are_reported_without_retry(self):
        self.current_checklist = checklist(targets={
            "BTCUSDT": 1,
            "ETHUSDT": 1,
            "BNBUSDT": 1,
            "SOLUSDT": 0.04,
            "XRPUSDT": 0.4,
        })
        self.gateway = Gateway({
            "ETHUSDT": {"executedQty": "0.5", "tradeQty": "0.5", "avgPrice": "10"},
            "BNBUSDT": RuntimeError("rejected"),
        })
        service = self.service(
            max_order_notional_usdt=100,
            round_gross_multiplier=2,
        )

        result = service.execute_due(self.sync)
        statuses = {row["symbol"]: row["status"] for row in result["report"]["rows"]}

        self.assertEqual(statuses["BTCUSDT"], "EXECUTED_MATCH")
        self.assertEqual(statuses["ETHUSDT"], "PARTIAL_FILL")
        self.assertEqual(statuses["BNBUSDT"], "ORDER_FAILED")
        self.assertEqual(statuses["SOLUSDT"], "SKIPPED_DUST")
        self.assertEqual(statuses["XRPUSDT"], "SKIPPED_BELOW_MIN")
        self.assertEqual(len(self.gateway.orders), 3)

    def test_trade_query_failure_preserves_successful_order_response(self):
        self.gateway = Gateway({
            "BTCUSDT": {
                "executedQty": "1",
                "avgPrice": "10.1",
                "tradeError": "temporary history failure",
            },
        })

        result = self.service().execute_due(self.sync)

        row = result["report"]["rows"][-1]
        self.assertEqual(result["status"], "COMPLETED_WITH_ERRORS")
        self.assertEqual(row["status"], "EXECUTED_MATCH")
        self.assertEqual(row["executed_quantity"], 1.0)
        self.assertEqual(row["fee"], 0.0)
        self.assertIn("USER_TRADES_QUERY_FAILED", row["error"])
        order_event = next(
            item["payload"] for item in self.ledger.read_all()
            if item["payload"]["event_type"] == "ORDER_RESULT"
        )
        self.assertEqual(order_event["exchange_response"]["executedQty"], "1")

    def test_notional_limits_and_drawdown_stop_before_orders(self):
        limit_result = self.service(
            max_order_notional_usdt=5,
        ).execute_due(self.sync)
        self.assertIn("MAX_ORDER_NOTIONAL_EXCEEDED", limit_result["reason"])
        self.assertEqual(self.gateway.orders, [])

        drawdown_ledger = AppendOnlyLiveExecutionLedger(
            Path(self.tmp.name) / "drawdown.jsonl"
        )
        drawdown = Equity([
            {"live_equity_usdt": 500, "paper_equity": 1.0},
            {"live_equity_usdt": 349, "paper_equity": 1.0},
        ])
        result = self.service(
            execution_ledger=drawdown_ledger,
            equity_ledger=drawdown,
        ).execute_due(self.sync)
        self.assertEqual(result["status"], "PROTOCOL_STOP")
        self.assertIn("LIVE_DRAWDOWN", result["reason"])
        self.assertEqual(self.gateway.orders, [])

        round_ledger = AppendOnlyLiveExecutionLedger(
            Path(self.tmp.name) / "round-limit.jsonl"
        )
        self.snapshot = account_snapshot(positions=[{
            "symbol": "BTCUSDT",
            "position_side": "BOTH",
            "position_amt": -1,
        }])
        result = self.service(
            execution_ledger=round_ledger,
        ).execute_due(self.sync)
        self.assertEqual(result["reason"], "MAX_ROUND_NOTIONAL_EXCEEDED")

        paper_ledger = AppendOnlyLiveExecutionLedger(
            Path(self.tmp.name) / "paper-drawdown.jsonl"
        )
        self.snapshot = account_snapshot()
        result = self.service(
            execution_ledger=paper_ledger,
            equity_ledger=Equity([
                {"live_equity_usdt": 500, "paper_equity": 1.0},
                {"live_equity_usdt": 500, "paper_equity": 0.69},
            ]),
        ).execute_due(self.sync)
        self.assertEqual(result["status"], "PROTOCOL_STOP")
        self.assertIn("PAPER_DRAWDOWN", result["reason"])

    def test_emergency_stop_and_injected_unmapped_order_latch_execution(self):
        service = self.service()
        stopped = service.emergency_stop(actor="admin_001", reason="operator stop")
        result = service.execute_due(self.sync)
        self.assertTrue(stopped["ok"])
        self.assertEqual(result["status"], "EMERGENCY_STOPPED")

        violation_ledger = AppendOnlyLiveExecutionLedger(
            Path(self.tmp.name) / "violation.jsonl"
        )
        violation_ledger.append({
            "protocol": "LIVE_SMALL_EXECUTION_V1",
            "event_type": "ORDER_RESULT",
            "execution_epoch": "pilot-001",
            "symbol": "NOT_IN_TB4",
            "order_intent": {"source": "OTHER"},
        })
        violation_service = self.service(execution_ledger=violation_ledger)
        violation = violation_service.execute_due(self.sync)
        again = violation_service.execute_due(self.sync)
        self.assertEqual(violation["status"], "PROTOCOL_VIOLATION")
        self.assertEqual(again["status"], "EMERGENCY_STOPPED")
        self.assertEqual(self.gateway.orders, [])

    def test_execution_ledger_detects_tampering(self):
        self.ledger.append({
            "protocol": "LIVE_SMALL_EXECUTION_V1",
            "event_type": "EMERGENCY_STOP",
            "execution_epoch": "pilot-001",
            "reason": "test",
        })
        record = json.loads(self.path.read_text(encoding="utf-8"))
        record["payload"]["reason"] = "changed"
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
            self.ledger.read_all()
        self.assertEqual(self.service().snapshot()["status"], "DATA_INTEGRITY_ERROR")
        result = self.service().execute_due(self.sync)
        self.assertEqual(result["status"], "DATA_INTEGRITY_ERROR")
        self.assertEqual(self.gateway.orders, [])

    def test_incomplete_claim_stops_later_round_after_restart(self):
        self.ledger.append({
            "protocol": "LIVE_SMALL_EXECUTION_V1",
            "event_type": "ROUND_STARTED",
            "execution_epoch": "pilot-001",
            "account_id": "live_001",
            "rebalance_time_ms": 100,
        })
        self.current_checklist = checklist(rebalance=200)
        service = self.service()

        result = service.execute_due(self.sync)

        self.assertEqual(result["status"], "PROTOCOL_STOP")
        self.assertEqual(result["reason"], "INCOMPLETE_ROUND_100")
        self.assertEqual(self.gateway.orders, [])


if __name__ == "__main__":
    unittest.main()
