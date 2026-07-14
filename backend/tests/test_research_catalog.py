import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.research.candidates import INITIAL_CANDIDATES
from orbit.application.research.catalog import ResearchCatalogService
from orbit.application.research.runs import CachedToolEvaluator, ResearchWorkflowService
from orbit.application.research.protocols import validate_datasets
from orbit.infrastructure.persistence.research_registry import AppendOnlyResearchRegistry
from orbit.infrastructure.persistence.research_runs import AppendOnlyResearchRunLedger


class FakeEvaluator:
    def evaluate(self, candidate, datasets, run_id):
        return {
            "reports": [
                {
                    "market": datasets[0]["market"],
                    "expected_value_pct": 0.25,
                    "trades": 12,
                }
            ]
        }

    def fetch_dataset(self, request, run_id):
        return f"{request['symbol']}_{run_id}_{request['kind']}"


class ResearchCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calibration_dir = self.root / "calibration"
        self.calibration_dir.mkdir()
        self.registry = AppendOnlyResearchRegistry(self.root / "research" / "registry.jsonl")
        self.run_ledger = AppendOnlyResearchRunLedger(self.root / "research" / "runs.jsonl")
        self.catalog = ResearchCatalogService(self.calibration_dir, self.registry, self.run_ledger)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dataset_catalog_returns_structured_metadata_and_fingerprint(self):
        rows = [
            {"open_time": 1000, "close": "10.0"},
            {"open_time": 2000, "close": "11.0"},
        ]
        path = self.calibration_dir / "BTCUSDT_4h_ohlc.json"
        path.write_text(json.dumps(rows), encoding="utf-8")
        (self.calibration_dir / "ignored_report.json").write_text(
            json.dumps({"verdict": "NO_GO"}),
            encoding="utf-8",
        )

        items = self.catalog.datasets()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["market"], "BTCUSDT")
        self.assertEqual(items[0]["interval"], "4h")
        self.assertEqual(items[0]["kind"], "ohlc")
        self.assertEqual(items[0]["rows"], 2)
        self.assertEqual(items[0]["start_time_ms"], 1000)
        self.assertEqual(items[0]["end_time_ms"], 2000)
        self.assertEqual(items[0]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

    def test_seed_candidates_have_frozen_hash_and_verdict(self):
        candidates = self.catalog.candidates()

        self.assertEqual([item["id"] for item in candidates], ["M0", "F1", "G1", "G2"])
        for candidate in candidates:
            self.assertEqual(len(candidate["frozen_hash"]), 64)
            self.assertEqual(candidate["verdict"], "NO_GO")
            self.assertEqual(candidate["status"], "evaluated")

    def test_frozen_candidate_cannot_be_changed_or_replaced(self):
        original = self.registry.append(INITIAL_CANDIDATES[0])
        changed = copy.deepcopy(INITIAL_CANDIDATES[0])
        changed["thresholds"] = {"required_positive_combinations": 2}

        with self.assertRaisesRegex(RuntimeError, "frozen"):
            self.registry.append(changed)
        with self.assertRaisesRegex(RuntimeError, "cannot be replaced"):
            self.registry.replace(original["id"], changed)

        self.assertEqual(self.registry.all(), [original])

    def test_result_read_model_returns_report_without_accepting_paths(self):
        report = {
            "protocol": "G2",
            "evidence_level": "training",
            "generated_at": "2026-07-13T00:00:00Z",
        }
        result_id = "g2_funding_relative_strength_training"
        (self.calibration_dir / f"{result_id}.json").write_text(
            "\n" + json.dumps(report),
            encoding="utf-8",
        )

        result = self.catalog.result(result_id)

        self.assertIsNotNone(result)
        self.assertEqual(result["verdict"], "NO_GO")
        self.assertEqual(result["report"], report)
        self.assertIsNone(self.catalog.result(f"../{result_id}"))

    def test_ui_candidate_is_frozen_with_dataset_fingerprints(self):
        path = self.calibration_dir / "BTCUSDT_1h_ohlc.json"
        path.write_text(json.dumps([[1000, 10], [2000, 11]]), encoding="utf-8")
        workflow = ResearchWorkflowService(
            self.catalog,
            self.run_ledger,
            FakeEvaluator(),
            submitter=lambda callback: callback(),
        )

        candidate = workflow.create_candidate({
            "id": "m0-next",
            "name": "Fresh M0",
            "protocol": "M0",
            "dataset_ids": ["BTCUSDT_1h_ohlc"],
        })

        self.assertEqual(candidate["status"], "frozen")
        self.assertEqual(candidate["verdict"], "PENDING")
        self.assertEqual(candidate["matrix"]["dataset_sha256"]["BTCUSDT_1h_ohlc"], hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(RuntimeError, "frozen"):
            workflow.create_candidate({
                "id": "m0-next",
                "name": "Changed",
                "protocol": "M0",
                "dataset_ids": ["BTCUSDT_1h_ohlc"],
            })

    def test_run_is_append_only_and_lockbox_can_open_only_once(self):
        (self.calibration_dir / "BTCUSDT_1h_ohlc.json").write_text(
            json.dumps([[1000, 10], [2000, 11]]),
            encoding="utf-8",
        )
        workflow = ResearchWorkflowService(
            self.catalog,
            self.run_ledger,
            FakeEvaluator(),
            submitter=lambda callback: callback(),
        )
        candidate = workflow.create_candidate({
            "id": "M0-LOCKBOX",
            "name": "One shot",
            "protocol": "M0",
            "dataset_ids": ["BTCUSDT_1h_ohlc"],
        })

        run = workflow.create_run(candidate["id"], open_lockbox=True)

        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["verdict"], "PASS")
        self.assertTrue(run["lockbox_opened_at"])
        result = self.catalog.result(run["result_id"])
        self.assertEqual(result["report"]["candidate_frozen_hash"], candidate["frozen_hash"])
        self.assertEqual(len(self.run_ledger._records()), 3)
        with self.assertRaisesRegex(RuntimeError, "already been opened"):
            workflow.create_run(candidate["id"], open_lockbox=True)

    def test_run_fails_if_cached_dataset_changes_after_freeze(self):
        path = self.calibration_dir / "BTCUSDT_1h_ohlc.json"
        path.write_text(json.dumps([[1000, 10], [2000, 11]]), encoding="utf-8")
        workflow = ResearchWorkflowService(
            self.catalog,
            self.run_ledger,
            FakeEvaluator(),
            submitter=lambda callback: callback(),
        )
        candidate = workflow.create_candidate({
            "id": "M0-DRIFT",
            "name": "Drift guard",
            "protocol": "M0",
            "dataset_ids": ["BTCUSDT_1h_ohlc"],
        })
        path.write_text(json.dumps([[1000, 99], [2000, 100]]), encoding="utf-8")

        run = workflow.create_run(candidate["id"])

        self.assertEqual(run["status"], "failed")
        self.assertIn("fingerprint changed", run["error"])

    def test_allowlisted_m0_tool_runs_against_cached_data_without_network(self):
        rows = [[index * 1000, 100 + (index % 8) - 4] for index in range(120)]
        (self.calibration_dir / "BTCUSDT_1h.json").write_text(json.dumps(rows), encoding="utf-8")
        workflow = ResearchWorkflowService(
            self.catalog,
            self.run_ledger,
            CachedToolEvaluator(BACKEND_ROOT.parent, self.calibration_dir),
            submitter=lambda callback: callback(),
        )
        candidate = workflow.create_candidate({
            "id": "M0-REAL-TOOL",
            "name": "Real cached tool",
            "protocol": "M0",
            "dataset_ids": ["BTCUSDT_1h"],
        })

        run = workflow.create_run(candidate["id"])

        self.assertEqual(run["status"], "succeeded")
        result = self.catalog.result(run["result_id"])
        self.assertEqual(len(result["report"]["reports"]), 4)

    def test_paired_protocol_rejects_mixed_candle_interval(self):
        datasets = [
            {"id": "BTC-funding", "market": "BTCUSDT", "kind": "funding", "interval": None},
            {"id": "BTC-4h", "market": "BTCUSDT", "kind": "ohlc", "interval": "4h"},
        ]

        with self.assertRaisesRegex(ValueError, "requires 15m"):
            validate_datasets(
                {"mode": "paired", "minimum_markets": 1, "candle_interval": "15m"},
                datasets,
            )

    def test_data_fetch_is_separate_job_and_validates_request(self):
        workflow = ResearchWorkflowService(
            self.catalog,
            self.run_ledger,
            FakeEvaluator(),
            submitter=lambda callback: callback(),
        )

        run = workflow.create_dataset_fetch({
            "symbol": "btcusdt",
            "kind": "ohlc",
            "interval": "15m",
            "days": 30,
        })

        self.assertEqual(run["status"], "succeeded")
        self.assertEqual(run["candidate_id"], "DATASET")
        self.assertIn("BTCUSDT", run["dataset_id"])
        with self.assertRaisesRegex(ValueError, "unsupported kline interval"):
            workflow.create_dataset_fetch({
                "symbol": "BTCUSDT",
                "kind": "ohlc",
                "interval": "2h",
                "days": 30,
            })

    def test_interrupted_run_is_failed_on_service_restart(self):
        created_at = "2026-07-14T00:00:00+00:00"
        self.run_ledger.append({
            "id": "run_interrupted",
            "candidate_id": "DATASET",
            "candidate_hash": "a" * 64,
            "protocol": "FETCH_KLINES",
            "status": "running",
            "progress": 10,
            "created_at": created_at,
            "updated_at": created_at,
        })

        ResearchWorkflowService(self.catalog, self.run_ledger, FakeEvaluator())

        recovered = self.run_ledger.get("run_interrupted")
        self.assertEqual(recovered["status"], "failed")
        self.assertIn("restarted", recovered["error"])


if __name__ == "__main__":
    unittest.main()
