import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ddg.binance import account_can_connect, fingerprint


class BinanceConnectorTest(unittest.TestCase):
    def test_fingerprint_is_short_and_stable(self):
        self.assertEqual(fingerprint("abc"), fingerprint("abc"))
        self.assertEqual(len(fingerprint("abc")), 16)

    def test_account_connection_flags_use_env_refs(self):
        account = {
            "api_key_ref": "env:DDG_TEST_MISSING_KEY",
            "secret_ref": "env:DDG_TEST_MISSING_SECRET",
        }
        status = account_can_connect(account)
        self.assertFalse(status["api_key_present"])
        self.assertFalse(status["secret_present"])
        self.assertEqual(status["api_key_env"], "DDG_TEST_MISSING_KEY")


if __name__ == "__main__":
    unittest.main()
