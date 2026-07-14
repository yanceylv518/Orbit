import json
import math
import tempfile
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.trend_forward import TrendForwardService
from orbit.application.trend_forward_market import TrendForwardMarketDriver
from orbit.domain.strategy.trend_basket_runner import TB4_SPEC
from orbit.infrastructure.persistence.trend_forward_ledger import TrendForwardLedger


def close_row(index):
    closes = {}
    for market_index, symbol in enumerate(TB4_SPEC.symbols):
        direction = 1 if market_index % 2 == 0 else -1
        closes[symbol] = (
            100 + market_index
        ) * math.exp(direction * 0.0008 * index + 0.003 * math.sin(index / 13))
    return {
        "close_time_ms": index * TB4_SPEC.interval_ms,
        "closes": closes,
        "funding_rates": {symbol: 0.000001 * (market_index - 5) for market_index, symbol in enumerate(TB4_SPEC.symbols)},
    }


class TrendForwardServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "tb4"
        self.warmup_count = TB4_SPEC.warmup_ticks + 1
        self.warmup = [close_row(index) for index in range(self.warmup_count)]
        self.start_time = self.warmup[-1]["close_time_ms"] + TB4_SPEC.interval_ms

    def tearDown(self):
        self.tmp.cleanup()

    def service(self):
        return TrendForwardService(TrendForwardLedger(self.path))

    def initialize(self, service):
        return service.initialize(
            start_time_ms=self.start_time,
            warmup_closes=self.warmup,
            input_fingerprints={symbol: f"sha-{symbol}" for symbol in TB4_SPEC.symbols},
            code_commit="test-commit",
            protocol_sha256="protocol-sha",
        )

    def test_warmup_is_not_scored_and_first_forward_close_is_scored(self):
        service = self.service()
        initialized = self.initialize(service)

        self.assertEqual(initialized["scored_periods"], 0)
        self.assertAlmostEqual(initialized["runner"]["equity"], 1.0)
        self.assertIsNone(initialized["verdict"])

        result = service.ingest_close(
            self.start_time,
            close_row(self.warmup_count)["closes"],
            close_row(self.warmup_count)["funding_rates"],
        )

        self.assertFalse(result["duplicate"])
        self.assertEqual(result["snapshot"]["scored_periods"], 1)
        self.assertEqual(result["snapshot"]["runner"]["rebalance_count"], 1)
        self.assertIsNone(result["snapshot"]["verdict"])

    def test_restart_replays_to_exact_same_state(self):
        uninterrupted = self.service()
        self.initialize(uninterrupted)
        for index in range(self.warmup_count, self.warmup_count + 5):
            row = close_row(index)
            uninterrupted.ingest_close(row["close_time_ms"], row["closes"], row["funding_rates"])
        before = uninterrupted.runner.export_state()

        restored = self.service()

        self.assertEqual(restored.runner.export_state(), before)
        self.assertEqual(restored.snapshot(), uninterrupted.snapshot())

    def test_manifest_is_immutable_and_duplicate_close_is_idempotent(self):
        service = self.service()
        self.initialize(service)
        with self.assertRaisesRegex(RuntimeError, "already initialized"):
            self.initialize(service)
        row = close_row(self.warmup_count)
        service.ingest_close(row["close_time_ms"], row["closes"], row["funding_rates"])
        count = service.snapshot()["ledger"]["event_count"]

        duplicate = service.ingest_close(row["close_time_ms"], row["closes"], row["funding_rates"])

        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(service.snapshot()["ledger"]["event_count"], count)

    def test_hash_chain_detects_modified_record(self):
        service = self.service()
        self.initialize(service)
        lines = (self.path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[-1])
        record["payload"]["closes"]["BTCUSDT"] += 1
        lines[-1] = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        (self.path / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "fingerprint mismatch"):
            self.service()

    def test_no_verdict_before_registered_minimum_duration(self):
        service = self.service()
        self.initialize(service)
        row = close_row(self.warmup_count)
        service.ingest_close(row["close_time_ms"], row["closes"], row["funding_rates"])

        snapshot = service.snapshot()

        self.assertEqual(snapshot["status"], "RUNNING")
        self.assertIsNone(snapshot["verdict"])
        self.assertFalse(snapshot["parameters_mutable"])
        self.assertFalse(snapshot["live_trading"])


class FakeTrendFeed:
    def __init__(self, rows):
        self.rows = rows

    def closed_klines(self, symbol, interval, limit):
        return self.rows[symbol][-limit:]

    def funding_rates(self, symbol, start_time_ms, end_time_ms):
        return [{
            "funding_time_ms": end_time_ms,
            "funding_rate": 0.000001,
        }]


class TrendForwardMarketDriverTest(unittest.TestCase):
    def test_initializes_common_history_and_polls_next_synchronized_close(self):
        with tempfile.TemporaryDirectory() as directory:
            required = TB4_SPEC.warmup_ticks + 1
            rows = {symbol: [] for symbol in TB4_SPEC.symbols}
            for index in range(required + 1):
                row = close_row(index)
                for symbol in TB4_SPEC.symbols:
                    rows[symbol].append({
                        "close_time": row["close_time_ms"],
                        "close": row["closes"][symbol],
                    })
            feed = FakeTrendFeed(rows)
            service = TrendForwardService(TrendForwardLedger(Path(directory) / "tb4"))
            driver = TrendForwardMarketDriver(feed, service)

            initialized = driver.initialize(code_commit="abc", protocol_sha256="protocol")
            self.assertEqual(initialized["scored_periods"], 0)
            next_row = close_row(required + 1)
            for symbol in TB4_SPEC.symbols:
                rows[symbol].append({
                    "close_time": next_row["close_time_ms"],
                    "close": next_row["closes"][symbol],
                })

            result = driver.poll_once()

            self.assertEqual(result["ticks"], 1)
            self.assertEqual(result["snapshot"]["scored_periods"], 1)


if __name__ == "__main__":
    unittest.main()
