import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.application.research.runs import CachedToolEvaluator, ResearchWorkflowService
from orbit.infrastructure.persistence.dataset_job_lock import (
    DatasetJobLock,
    DatasetJobLockBusy,
)
from orbit.infrastructure.persistence.research_runs import AppendOnlyResearchRunLedger


class RecordingEvaluator(CachedToolEvaluator):
    def __init__(self, project_root, calibration_dir):
        super().__init__(
            project_root, calibration_dir,
            shortline_min_free_gb=0,
            shortline_verify_sample_symbols=2,
        )
        self.commands = []

    def _run_shortline_phase(self, command, **kwargs):
        self.commands.append((kwargs["phase"], command))
        kwargs["on_progress"]({"phase": kwargs["phase"], "progress": kwargs["end_progress"]})


class DatasetJobLockTests(unittest.TestCase):
    def test_data1r_failure_cannot_modify_tb4_runtime_files(self):
        class FailingEvaluator(RecordingEvaluator):
            def _run_shortline_phase(self, command, **kwargs):
                self.shortline_root.mkdir(parents=True, exist_ok=True)
                (self.shortline_root / "failure-marker.json").write_text(
                    json.dumps({"phase": kwargs["phase"]}), encoding="utf-8",
                )
                raise RuntimeError("injected DATA-1R failure")

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            calibration = project / "var" / "calibration"
            tb4 = project / "var" / "forward" / "tb4"
            tb4.mkdir(parents=True)
            manifest = tb4 / "manifest.json"
            events = tb4 / "events.jsonl"
            manifest.write_bytes(b'{"immutable":"manifest"}\n')
            events.write_bytes(b'{"immutable":"event"}\n')
            before = {path.name: path.read_bytes() for path in (manifest, events)}
            evaluator = FailingEvaluator(project, calibration)
            evaluator.reserve_shortline_dataset("run-failure")

            with self.assertRaisesRegex(RuntimeError, "injected DATA-1R failure"):
                evaluator.build_shortline_dataset(
                    {"workers": 1}, "run-failure", lambda _item: None,
                )

            self.assertTrue((evaluator.shortline_root / "failure-marker.json").is_file())
            self.assertEqual(
                {path.name: path.read_bytes() for path in (manifest, events)},
                before,
            )

    def test_lock_excludes_cli_and_ui_and_exposes_holder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "shortline-data-v1"
            cli = DatasetJobLock(root, owner="cli:sync")
            holder = cli.acquire()
            try:
                self.assertEqual(holder["owner"], "cli:sync")
                self.assertEqual(DatasetJobLock.read_holder(root)["token"], cli.token)
                evaluator = CachedToolEvaluator(
                    Path(temp), Path(temp), shortline_min_free_gb=0,
                )
                with self.assertRaises(DatasetJobLockBusy):
                    evaluator.reserve_shortline_dataset("run-ui")
            finally:
                cli.release()
            ui = DatasetJobLock(root, owner="orbit-ui", run_id="run-ui")
            ui.acquire()
            ui.release()

    def test_real_cli_is_rejected_while_ui_holds_dataset_lock(self):
        calibration = PROJECT_ROOT / "var" / "calibration"
        calibration.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=calibration) as temp:
            root = Path(temp) / "shortline-data-v1"
            ui = DatasetJobLock(root, owner="orbit-ui", run_id="run-ui")
            ui.acquire()
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(BACKEND_ROOT / "tools" / "shortline_dataset.py"),
                        "--root", str(root), "index", "--symbol", "LUNAUSDT",
                    ],
                    cwd=PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                )
            finally:
                ui.release()
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("locked by orbit-ui", completed.stderr)

    def test_disk_and_runtime_guards_block_before_job_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            disabled = CachedToolEvaluator(root, root, shortline_enabled=False)
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                disabled.reserve_shortline_dataset("disabled")
            low_disk = CachedToolEvaluator(
                root, root, shortline_min_free_gb=15,
                disk_usage=lambda _path: SimpleNamespace(free=1024),
            )
            with self.assertRaisesRegex(RuntimeError, "at least 15.0 GB"):
                low_disk.reserve_shortline_dataset("low-disk")

    def test_ui_pipeline_uses_locked_root_and_native_verification_phase(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            calibration = project / "calibration"
            evaluator = RecordingEvaluator(project, calibration)
            evaluator.reserve_shortline_dataset("run-1")
            evaluator.shortline_root.mkdir(parents=True, exist_ok=True)
            (evaluator.shortline_root / "manifest.json").write_text(json.dumps({
                "dataset_state": "COMPLETE",
                "dataset_fingerprint": "a" * 64,
                "quality_report_sha256": "b" * 64,
            }), encoding="utf-8")
            (evaluator.shortline_root / "quality_report.json").write_text(json.dumps({
                "contract_count": 2,
                "partition_count": 4,
            }), encoding="utf-8")

            result = evaluator.build_shortline_dataset(
                {"workers": 4}, "run-1", lambda _item: None,
            )

            self.assertEqual([item[0] for item in evaluator.commands], [
                "index", "download", "build", "verify",
            ])
            verify_command = evaluator.commands[-1][1]
            self.assertIn("verify-batch", verify_command)
            self.assertIn("--lock-owner-token", verify_command)
            self.assertIn(str(evaluator.shortline_root), verify_command)
            self.assertEqual(result["dataset_state"], "COMPLETE")
            self.assertIsNone(DatasetJobLock.read_holder(evaluator.shortline_root))

    def test_workflow_reserves_lock_before_background_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            calibration = project / "calibration"
            evaluator = RecordingEvaluator(project, calibration)
            evaluator.shortline_root.mkdir(parents=True, exist_ok=True)
            (evaluator.shortline_root / "manifest.json").write_text(json.dumps({
                "dataset_state": "COMPLETE",
                "dataset_fingerprint": "a" * 64,
                "quality_report_sha256": "b" * 64,
            }), encoding="utf-8")
            (evaluator.shortline_root / "quality_report.json").write_text(json.dumps({
                "contract_count": 2,
                "partition_count": 4,
            }), encoding="utf-8")
            ledger = AppendOnlyResearchRunLedger(project / "runs.jsonl")
            workflow = ResearchWorkflowService(
                SimpleNamespace(), ledger, evaluator,
                submitter=lambda callback: callback(),
            )

            run = workflow.create_shortline_dataset_build({
                "confirm_full_download": True,
                "workers": 2,
            })

            self.assertEqual(run["status"], "succeeded")
            self.assertEqual(run["lock_holder"]["owner"], "orbit-ui")
            self.assertEqual([item[0] for item in evaluator.commands], [
                "index", "download", "build", "verify",
            ])


if __name__ == "__main__":
    unittest.main()
