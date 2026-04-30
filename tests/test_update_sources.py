import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from back.init_db import connect_db, init_db  # noqa: E402
from back.update_sources import ask_parser_config, parse_json_value, save_source  # noqa: E402


TEST_DB_PATH = PROJECT_ROOT / "tests" / ".tmp" / "update_sources_test.db"


class UpdateSourcesTest(unittest.TestCase):
    def setUp(self):
        TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()
        init_db(TEST_DB_PATH, seed_initial_source=False)

    def tearDown(self):
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()

    def test_parse_json_value(self):
        self.assertEqual(parse_json_value('["article p", "article h1"]'), ["article p", "article h1"])
        self.assertEqual(parse_json_value('"article p"'), "article p")
        self.assertIsNone(parse_json_value("null"))

    def test_save_source_inserts_and_updates_by_url(self):
        config = {"max_age_days": 2, "link_selector": "a"}

        first = {
            "name": "First",
            "url": "https://example.com",
            "source_type": "site",
            "is_active": True,
            "parse_frequency_minutes": 60,
        }
        second = {
            "name": "Second",
            "url": "https://example.com",
            "source_type": "rss",
            "is_active": False,
            "parse_frequency_minutes": 30,
        }

        first_id = save_source(TEST_DB_PATH, first, config)
        second_id = save_source(TEST_DB_PATH, second, config)

        with connect_db(TEST_DB_PATH) as db:
            rows = db.execute("SELECT * FROM sources").fetchall()

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Second")
        self.assertEqual(rows[0]["source_type"], "rss")
        self.assertEqual(rows[0]["is_active"], 0)
        self.assertEqual(json.loads(rows[0]["parser_config"]), config)


if __name__ == "__main__":
    unittest.main()
