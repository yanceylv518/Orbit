import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "config" / "research" / "r0_shortline_screen.v1.json"
DOC_PATH = ROOT / "docs" / "design" / "R0_SHORTLINE_SCREEN.md"
FORMAL_MANIFEST_PATH = ROOT / "var" / "calibration" / "shortline-data-v1" / "manifest.json"


class R0PreregistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = SPEC_PATH.read_bytes()
        cls.spec = json.loads(cls.raw.decode("utf-8"))

    def test_protocol_is_frozen_before_signal_evaluation(self):
        self.assertEqual(self.spec["protocol"], "ORBIT_R0_SHORTLINE_SCREEN_V1")
        self.assertEqual(self.spec["status"], "FROZEN_BEFORE_SIGNAL_EVALUATION")
        self.assertIn(
            "NO_SIGNAL_OR_RETURN_READ_BEFORE_THIS_PROTOCOL_IS_COMMITTED",
            self.spec["prohibitions"],
        )

    def test_dataset_and_time_lockbox_are_exact(self):
        dataset = self.spec["dataset"]
        split = self.spec["sample_split"]
        self.assertEqual(
            dataset["manifest_fingerprint"],
            "dcb60c95ecd796e9ade32fcc8bf600a958ba7e88c47a2fdbd7d55569b56ca546",
        )
        self.assertEqual(
            dataset["quality_report_sha256"],
            "f5885005ebd245e79cfd1a2a7afb13837be5048b952c9bae02b9682c6638710f",
        )
        self.assertEqual(split["training_end_ms"] + 1, split["lockbox_start_ms"])
        self.assertEqual(split["lockbox_end_ms"], dataset["dataset_cutoff_ms"])

    def test_two_small_frozen_grids_do_not_expand_search_space(self):
        families = self.spec["families"]
        self.assertEqual([item["id"] for item in families], [
            "BREAKOUT_MOMENTUM",
            "OVERSOLD_REBOUND",
        ])
        self.assertEqual(sum(
            definition["grid_size"]
            for family in families
            for definition in family["definitions"]
        ), 16)
        self.assertEqual(len(families[0]["definitions"]), 1)
        self.assertEqual(len(families[1]["definitions"]), 1)

    def test_costs_and_robustness_gates_are_frozen(self):
        costs = self.spec["execution"]["costs_pct_per_side_by_tier"]
        self.assertEqual([item["round_trip"] for item in costs], ["0.16", "0.25", "0.40"])
        statistics = self.spec["statistics"]
        self.assertEqual(statistics["bootstrap_samples"], 10_000)
        self.assertEqual(statistics["bootstrap_seed"], 20_260_811)
        for gate_name in ("training_gates", "lockbox_gates"):
            gates = statistics[gate_name]
            self.assertEqual(gates["bootstrap_mean_lower_bound_gt_pct"], "0")
            self.assertEqual(gates["leave_one_tier_out_mean_gt_pct"], "0")
            self.assertEqual(gates["leave_one_year_out_mean_gt_pct"], "0")

    def test_document_points_to_the_exact_machine_contract(self):
        document = DOC_PATH.read_text(encoding="utf-8")
        spec_sha256 = hashlib.sha256(self.raw).hexdigest()
        self.assertIn("r0_shortline_screen.v1.json", document)
        self.assertIn(self.spec["dataset"]["manifest_fingerprint"], document)
        self.assertIn(self.spec["dataset"]["quality_report_sha256"], document)
        self.assertIn("FROZEN_BEFORE_SIGNAL_EVALUATION", document)
        self.assertEqual(
            spec_sha256,
            "1e6574850cc13a7cde217ec292c953a36c52a7a24455f3101d13f634faacc8be",
        )
        self.assertIn(spec_sha256, document)

    def test_contract_matches_formal_data_machine_when_dataset_is_present(self):
        if not FORMAL_MANIFEST_PATH.exists():
            self.skipTest("formal dataset is intentionally not stored in git")
        manifest = json.loads(FORMAL_MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            self.spec["dataset"]["manifest_fingerprint"],
            manifest["dataset_fingerprint"],
        )
        self.assertEqual(
            self.spec["dataset"]["quality_report_sha256"],
            manifest["quality_report_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
