import json
import re
import sqlite3
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from back.init_db import connect_db, init_db  # noqa: E402


TEST_DB_PATH = PROJECT_ROOT / "tests" / ".tmp" / "test.db"


README_PATH = PROJECT_ROOT / "data" / "README.md"


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.db_path = TEST_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            self.db_path.unlink()
        init_db(self.db_path, seed_initial_source=False)

    def tearDown(self):
        if self.db_path.exists():
            self.db_path.unlink()

    def test_schema_has_all_readme_columns(self):
        expected_columns = read_readme_columns()

        with connect_db(self.db_path) as db:
            tables = {
                row["name"]
                for row in db.execute("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                """)
            }

            for table_name, table_columns in expected_columns.items():
                self.assertIn(table_name, tables)
                actual_columns = [
                    row["name"]
                    for row in db.execute(f"PRAGMA table_info({table_name})")
                ]
                self.assertEqual(actual_columns, table_columns)

    def test_parser_and_model_can_write_and_read_data(self):
        with connect_db(self.db_path) as db:
            source_id = self._insert_source(db)
            active_source = db.execute("""
                SELECT id, name, url, source_type
                FROM sources
                WHERE is_active = 1
            """).fetchone()

            self.assertEqual(active_source["id"], source_id)
            self.assertEqual(active_source["name"], "VC Finance")

            raw_news_id = self._insert_raw_news(db, source_id)
            raw_news = db.execute("""
                SELECT id, source_id, url, title, text, raw_data, status
                FROM raw_news
                WHERE status = 'new'
            """).fetchone()

            self.assertEqual(raw_news["id"], raw_news_id)
            self.assertEqual(raw_news["source_id"], source_id)
            self.assertEqual(raw_news["status"], "new")
            self.assertEqual(json.loads(raw_news["raw_data"])["parser"], "test")

            db.execute("UPDATE raw_news SET status = 'processing' WHERE id = ?", (raw_news_id,))
            signal_id = self._insert_signal(db, raw_news_id)
            db.execute("UPDATE raw_news SET status = 'processed' WHERE id = ?", (raw_news_id,))
            db.commit()

            card = db.execute("""
                SELECT
                    signals.id,
                    signals.headline,
                    signals.hotness,
                    signals.category,
                    raw_news.status AS raw_status,
                    raw_news.url AS source_url,
                    sources.name AS source_name
                FROM signals
                JOIN raw_news ON raw_news.id = signals.raw_news_id
                JOIN sources ON sources.id = raw_news.source_id
                WHERE signals.id = ?
            """, (signal_id,)).fetchone()

            self.assertEqual(card["headline"], "New payment service")
            self.assertEqual(card["hotness"], 80)
            self.assertEqual(card["category"], "payment_service")
            self.assertEqual(card["raw_status"], "processed")
            self.assertEqual(card["source_url"], "https://example.com/news/1")
            self.assertEqual(card["source_name"], "VC Finance")

    def test_parser_can_ignore_duplicate_news_url(self):
        with connect_db(self.db_path) as db:
            source_id = self._insert_source(db)
            self._insert_raw_news(db, source_id)

            db.execute("""
                INSERT OR IGNORE INTO raw_news (
                    source_id,
                    url,
                    title,
                    text,
                    content_hash
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                source_id,
                "https://example.com/news/1",
                "Duplicate",
                "Duplicate text",
                "duplicate-hash",
            ))
            db.commit()

            count = db.execute("SELECT COUNT(*) AS count FROM raw_news").fetchone()["count"]
            self.assertEqual(count, 1)

    def test_foreign_keys_are_enforced(self):
        with connect_db(self.db_path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""
                    INSERT INTO raw_news (source_id, url, text)
                    VALUES (?, ?, ?)
                """, (999, "https://example.com/no-source", "text"))

    def test_foreign_keys_reject_invalid_signal_parent(self):
        with connect_db(self.db_path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("""
                    INSERT INTO signals (raw_news_id, headline, hotness, category)
                    VALUES (?, ?, ?, ?)
                """, (999, "No parent", 50, "payment_service"))

    def test_defaults_are_applied(self):
        with connect_db(self.db_path) as db:
            source_id = self._insert_source(db)
            raw_news_id = self._insert_raw_news(db, source_id)
            signal_id = self._insert_signal(db, raw_news_id)

            source = db.execute("SELECT is_active, parse_frequency_minutes FROM sources WHERE id = ?", (source_id,)).fetchone()
            raw_news = db.execute("SELECT status, parsed_at FROM raw_news WHERE id = ?", (raw_news_id,)).fetchone()
            signal = db.execute("SELECT moderation_status, created_at FROM signals WHERE id = ?", (signal_id,)).fetchone()

            self.assertEqual(source["is_active"], 1)
            self.assertEqual(source["parse_frequency_minutes"], 60)
            self.assertEqual(raw_news["status"], "new")
            self.assertIsNotNone(raw_news["parsed_at"])
            self.assertEqual(signal["moderation_status"], "pending")
            self.assertIsNotNone(signal["created_at"])

    def test_deleting_source_cascades_to_news_and_signals(self):
        with connect_db(self.db_path) as db:
            source_id = self._insert_source(db)
            raw_news_id = self._insert_raw_news(db, source_id)
            self._insert_signal(db, raw_news_id)

            db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            db.commit()

            raw_count = db.execute("SELECT COUNT(*) AS count FROM raw_news").fetchone()["count"]
            signal_count = db.execute("SELECT COUNT(*) AS count FROM signals").fetchone()["count"]

            self.assertEqual(raw_count, 0)
            self.assertEqual(signal_count, 0)

    def test_expected_indexes_exist(self):
        with connect_db(self.db_path) as db:
            indexes = {
                row["name"]
                for row in db.execute("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'index'
                """)
            }

            self.assertIn("idx_raw_news_status", indexes)
            self.assertIn("idx_raw_news_content_hash", indexes)

    def test_initial_source_is_seeded_with_parser_config(self):
        init_db(self.db_path, seed_initial_source=True)

        with connect_db(self.db_path) as db:
            source = db.execute("""
                SELECT id, name, url, parser_config
                FROM sources
                WHERE id = 1
            """).fetchone()

        config = json.loads(source["parser_config"])
        self.assertEqual(source["id"], 1)
        self.assertEqual(source["name"], "RBC Trends Fintech")
        self.assertEqual(source["url"], "https://trends.rbc.ru/trends/tag/fintech")
        self.assertEqual(config["max_age_days"], 2)
        self.assertEqual(config["link_selector"], "a.g-inline-text-badges.js-item-link")
        self.assertIsNone(config["date_selectors"])
        self.assertEqual(config["text_selector"], "article p")
        self.assertEqual(config["pause"], 0.5)
        self.assertEqual(config["timeout"], 15)
        self.assertTrue(config["use_fallback_date_search"])
        self.assertIsNone(config["date_formats"])

    def _insert_source(self, db):
        cursor = db.execute("""
            INSERT INTO sources (name, url, source_type)
            VALUES (?, ?, ?)
        """, ("VC Finance", "https://vc.ru/finance", "site"))
        db.commit()
        return cursor.lastrowid

    def _insert_raw_news(self, db, source_id):
        cursor = db.execute("""
            INSERT INTO raw_news (
                source_id,
                url,
                title,
                text,
                published_at,
                content_hash,
                raw_data
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            source_id,
            "https://example.com/news/1",
            "News",
            "News text",
            "2026-04-30 10:00:00",
            "content-hash",
            json.dumps({"parser": "test"}, ensure_ascii=False),
        ))
        db.commit()
        return cursor.lastrowid

    def _insert_signal(self, db, raw_news_id):
        cursor = db.execute("""
            INSERT INTO signals (
                raw_news_id,
                headline,
                hotness,
                why_now,
                category,
                summary,
                draft,
                confidence,
                model_name,
                prompt_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            raw_news_id,
            "New payment service",
            80,
            "The signal appeared today",
            "payment_service",
            "Short summary",
            "Draft post",
            0.9,
            "test-model",
            "v1",
        ))
        db.commit()
        return cursor.lastrowid


def read_readme_columns():
    readme = README_PATH.read_text(encoding="utf-8")
    result = {}

    for table_name in ("sources", "raw_news", "signals"):
        match = re.search(
            rf"### `{table_name}`(?P<section>.*?)(?=\n### `|\n## |\Z)",
            readme,
            flags=re.S,
        )
        if not match:
            raise AssertionError(f"README section for {table_name} not found")

        result[table_name] = re.findall(r"^\| `([^`]+)` \|", match.group("section"), flags=re.M)

    return result


if __name__ == "__main__":
    unittest.main()
