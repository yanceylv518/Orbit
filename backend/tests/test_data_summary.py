import json
import tempfile
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.data_summary import DataSummaryError, DataSummaryService


class DataSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "shortline-data-v1"
        (self.root / "metadata").mkdir(parents=True)
        self.service = DataSummaryService(self.root)
        self._write_fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_fixture(self):
        cutoff = 2000
        halt = {
            "id": "OLDUSDT-halt",
            "symbol": "OLDUSDT",
            "month": "2026-01",
            "start_open_time_ms": 1000,
            "end_open_time_ms": 1000,
            "count": 1,
            "classification": "EXCHANGE_HALT",
        }
        quality = {
            "protocol": "ORBIT_SHORTLINE_DATASET_V1",
            "dataset_cutoff_ms": cutoff,
            "dataset_state": "COMPLETE",
            "contract_count": 2,
            "partition_count": 2,
            "report_sha256": "quality-hash",
            "verified_halt_windows": [halt],
            "archive_coverage": {"complete": True},
            "partitions": [
                {
                    "symbol": "OLDUSDT",
                    "month": "2026-01",
                    "missing_ranges": [{
                        "start_open_time_ms": 1000,
                        "end_open_time_ms": 1000,
                        "count": 1,
                    }],
                    "duplicate_count": 0,
                },
                {
                    "symbol": "BTCUSDT",
                    "month": "2026-01",
                    "missing_ranges": [],
                    "duplicate_count": 2,
                },
            ],
            "summary": {
                "missing_15m_candles": 1,
                "unverified_missing_15m_candles": 0,
                "duplicate_15m_candles": 2,
                "verified_halt_window_count": 1,
                "verified_halt_missing_candles": 1,
                "incomplete_15m_partitions": 1,
                "funding_symbols": 2,
                "missing_funding_symbols": [],
            },
        }
        manifest = {
            "protocol": "ORBIT_SHORTLINE_DATASET_V1",
            "dataset_cutoff_ms": cutoff,
            "dataset_state": "COMPLETE",
            "dataset_fingerprint": "dataset-hash",
            "quality_report_sha256": "quality-hash",
        }
        contracts = {
            "protocol": "ORBIT_SHORTLINE_DATASET_V1",
            "dataset_cutoff_ms": cutoff,
            "contracts": [
                {"symbol": "BTCUSDT", "status": "TRADING"},
                {"symbol": "OLDUSDT", "status": "DELISTED"},
            ],
        }
        (self.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.root / "quality_report.json").write_text(json.dumps(quality), encoding="utf-8")
        (self.root / "metadata" / "contracts.json").write_text(
            json.dumps(contracts), encoding="utf-8"
        )

    def test_summary_projects_frozen_report_values_without_recalculation(self):
        summary = self.service.summary()

        self.assertEqual(summary["dataset_cutoff_ms"], 2000)
        self.assertEqual(summary["contracts"], {"total": 2, "trading": 1, "delisted": 1})
        self.assertEqual(summary["quality"]["unverified_missing_15m_candles"], 0)
        self.assertEqual(summary["quality"]["duplicate_15m_candles"], 2)
        self.assertEqual(summary["quality"]["verified_halt_windows"], 1)

    def test_quality_details_are_paginated_and_halts_explain_matching_gaps(self):
        missing = self.service.quality_page("missing", page=1, page_size=1)
        duplicates = self.service.quality_page("duplicates", page=1, page_size=50)

        self.assertEqual(missing["total"], 1)
        self.assertTrue(missing["items"][0]["explained_by_halt"])
        self.assertEqual(duplicates["items"][0]["duplicate_candles"], 2)

    def test_cache_returns_isolated_values_and_invalidates_when_report_changes(self):
        first = self.service.summary()
        first["contracts"]["total"] = 999
        self.assertEqual(self.service.summary()["contracts"]["total"], 2)

        quality_path = self.root / "quality_report.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        quality["summary"]["duplicate_15m_candles"] = 3
        quality_path.write_text(json.dumps(quality, indent=2), encoding="utf-8")
        self.assertEqual(self.service.summary()["quality"]["duplicate_15m_candles"], 3)

    def test_mismatched_quality_fingerprint_is_rejected(self):
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["quality_report_sha256"] = "different"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with self.assertRaisesRegex(DataSummaryError, "fingerprint"):
            self.service.summary()


if __name__ == "__main__":
    unittest.main()
