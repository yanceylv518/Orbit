import sys
import unittest
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from migrate_config_directory_to_mysql import migration_payload, user_mapping
from orbit.config import load_config


class DirectoryMigrationTest(unittest.TestCase):
    def test_user_mapping_rewrites_all_directory_references(self):
        config = load_config(str(ROOT / "config" / "config.sample.json"))

        payload = migration_payload(
            config,
            user_mapping(["user_001=lyfei"]),
        )

        self.assertEqual(
            {user["id"] for user in payload["users"]},
            {"admin_001", "lyfei"},
        )
        self.assertEqual(
            payload["exchange_accounts"][0]["user_id"],
            "lyfei",
        )
        self.assertEqual(
            payload["strategy_instance"]["user_id"],
            "lyfei",
        )

    def test_invalid_user_mapping_is_rejected(self):
        with self.assertRaises(SystemExit):
            user_mapping(["missing-separator"])


if __name__ == "__main__":
    unittest.main()
