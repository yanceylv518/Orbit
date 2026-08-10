import sys
from pathlib import Path
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from orbit.infrastructure.persistence.atomic_file import replace_with_retry


class AtomicFileTests(unittest.TestCase):
    def test_replace_retries_transient_windows_permission_error(self):
        with (
            patch(
                "orbit.infrastructure.persistence.atomic_file.os.replace",
                side_effect=[PermissionError("busy"), None],
            ) as replace,
            patch("orbit.infrastructure.persistence.atomic_file.time.sleep") as sleep,
        ):
            replace_with_retry(Path("state.tmp"), Path("state.json"), attempts=2)

        self.assertEqual(replace.call_count, 2)
        sleep.assert_called_once_with(0.05)

    def test_replace_raises_after_retry_budget_is_exhausted(self):
        with (
            patch(
                "orbit.infrastructure.persistence.atomic_file.os.replace",
                side_effect=PermissionError("still busy"),
            ) as replace,
            patch("orbit.infrastructure.persistence.atomic_file.time.sleep"),
        ):
            with self.assertRaises(PermissionError):
                replace_with_retry(Path("state.tmp"), Path("state.json"), attempts=3)

        self.assertEqual(replace.call_count, 3)


if __name__ == "__main__":
    unittest.main()
