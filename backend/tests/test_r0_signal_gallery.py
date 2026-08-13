from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from orbit.application.r0_signal_gallery import (
    R0SignalGalleryError,
    R0SignalGalleryStore,
    canonical_sha256,
    deterministic_sample,
)


class R0SignalGalleryTests(unittest.TestCase):
    def test_sampling_is_deterministic_disjoint_and_bounded(self):
        events = [self._event(index) for index in range(1000)]
        first = deterministic_sample(events, "P:1", seed=17, count=24)
        second = deterministic_sample(list(reversed(events)), "P:1", seed=17, count=24)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 72)
        self.assertEqual(len({item["event_id"] for item in first}), 72)
        self.assertEqual({item["sample_stratum"] for item in first}, {
            "BOTTOM_NET_RETURN", "TOP_NET_RETURN", "DETERMINISTIC_RANDOM",
        })

    def test_store_reads_only_requested_parameter_file(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = self._store(root, [self._sample(2021)])
            untouched = store.gallery_root / "P_2.json"
            untouched.write_text("not-json", encoding="utf-8")
            result = store.samples("P:1", {"limit": 24})
            self.assertEqual(len(result["items"]), 1)

    def test_lockbox_event_is_rejected_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sample = self._sample(2025)
            sample["signal_time_ms"] = 1735689600000
            store = self._store(root, [sample])
            with self.assertRaises(R0SignalGalleryError):
                store.samples("P:1", {})

    def test_filters_and_limit_never_expand_the_frozen_sample(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            samples = [self._sample(2021), self._sample(2022, recovered=True)]
            store = self._store(root, samples)
            result = store.samples("P:1", {"cohort": "STOP_THEN_RECOVERED", "year": 2022, "limit": 999})
            self.assertEqual([item["entry_year_utc"] for item in result["items"]], [2022])
            self.assertLessEqual(len(result["items"]), 24)

    @staticmethod
    def _event(index):
        return {
            "symbol": f"S{index % 17}", "entry_time_ms": index * 1000,
            "exit_time_ms": index * 1000 + 1, "net_return_pct": index - 500,
        }

    @staticmethod
    def _sample(year, recovered=False):
        return {
            "event_id": f"e-{year}", "signal_time_ms": 1600000000000,
            "entry_year_utc": year, "net_return_pct": 1,
            "tier": "HIGH", "volume_trend_3d": "STRICTLY_INCREASING",
            "listing_age": "GT_30_DAYS", "stop_then_recovered_2h": recovered,
        }

    def _store(self, root, samples):
        config = root / "config" / "research"
        gallery = root / "docs" / "evidence" / "r0" / "signal_gallery"
        config.mkdir(parents=True)
        gallery.mkdir(parents=True)
        contract = {
            "protocol": "ORBIT_R0_SIGNAL_GALLERY_V1", "lockbox_access": "PROHIBITED",
            "dataset_fingerprint": "d", "training_report_git_sha256": "t",
            "lockbox_start_ms": 1735689600000, "sampling": {}, "window": {},
        }
        contract_path = config / "r0_signal_gallery.v1.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        parameter = {
            "parameter_id": "P:1", "family_id": "F", "parameters": {}, "samples": samples,
        }
        parameter_path = gallery / "P_1.json"
        parameter_path.write_text(json.dumps(parameter), encoding="utf-8")
        manifest = {
            "protocol": "ORBIT_R0_SIGNAL_GALLERY_REPORT_V1",
            "gallery_contract_sha256": canonical_sha256(contract_path),
            "dataset_fingerprint": "d", "training_report_sha256": "t",
            "lockbox_opened": False,
            "parameter_reports": [{"parameter_id": "P:1", "file": "P_1.json", "sha256": canonical_sha256(parameter_path)}],
        }
        (gallery / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return R0SignalGalleryStore(root)


if __name__ == "__main__":
    unittest.main()
