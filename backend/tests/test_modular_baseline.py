from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.domain.strategy.trend_basket_runner import tb4_spec_fingerprint
from orbit.infrastructure.persistence.trend_forward_ledger import TrendForwardLedger


class ModularBaselineTests(unittest.TestCase):
    def test_checked_in_runtime_baseline_matches_frozen_tb4(self):
        completed = subprocess.run(
            [sys.executable, str(BACKEND_ROOT / "tools" / "verify_modular_baseline.py")],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("MODULAR_BASELINE_PASS", completed.stdout)

    def test_runtime_manifest_is_checked_without_being_modified(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "tb4"
            ledger = TrendForwardLedger(runtime)
            manifest = ledger.create_manifest({
                "protocol": "TB4_FORWARD_V1",
                "spec_sha256": tb4_spec_fingerprint(),
            })
            ledger.append({"event": "baseline"})
            before_manifest = ledger.manifest_path.read_bytes()
            before_events = ledger.events_path.read_bytes()

            completed = subprocess.run(
                [
                    sys.executable,
                    str(BACKEND_ROOT / "tools" / "verify_modular_baseline.py"),
                    "--runtime-dir", str(runtime),
                    "--require-runtime",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout.split("\nMODULAR_BASELINE_PASS", 1)[0])
            self.assertEqual(report["runtime"]["manifest_sha256"], manifest["manifest_sha256"])
            self.assertEqual(ledger.manifest_path.read_bytes(), before_manifest)
            self.assertEqual(ledger.events_path.read_bytes(), before_events)


if __name__ == "__main__":
    unittest.main()
