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
from orbit.infrastructure.persistence.research_registry import AppendOnlyResearchRegistry


class ResearchCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calibration_dir = self.root / "calibration"
        self.calibration_dir.mkdir()
        self.registry = AppendOnlyResearchRegistry(self.root / "research" / "registry.jsonl")
        self.catalog = ResearchCatalogService(self.calibration_dir, self.registry)

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


if __name__ == "__main__":
    unittest.main()
