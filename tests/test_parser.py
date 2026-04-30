import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import back.parser as parser_module  # noqa: E402
from back.init_db import connect_db, init_db  # noqa: E402


TEST_DB_PATH = PROJECT_ROOT / "tests" / ".tmp" / "parser_test.db"


class ParserDatabaseTest(unittest.TestCase):
    def setUp(self):
        TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()
        init_db(TEST_DB_PATH, seed_initial_source=False)

    def tearDown(self):
        if TEST_DB_PATH.exists():
            TEST_DB_PATH.unlink()

    def test_parser_reads_sources_and_writes_raw_news(self):
        original_parser = parser_module.NewsParser
        parser_module.NewsParser = FakeNewsParser
        try:
            with connect_db(TEST_DB_PATH) as db:
                db.execute("""
                    INSERT INTO sources (name, url, parser_config)
                    VALUES (?, ?, ?)
                """, (
                    "Fake Source",
                    "https://example.com",
                    json.dumps({"max_age_days": 1}),
                ))
                db.commit()

            result = parser_module.run_parser_from_db(TEST_DB_PATH)

            with connect_db(TEST_DB_PATH) as db:
                raw_news = db.execute("""
                    SELECT source_id, url, title, text, published_at, status
                    FROM raw_news
                """).fetchone()
                source = db.execute("SELECT last_parsed_at FROM sources WHERE id = 1").fetchone()
        finally:
            parser_module.NewsParser = original_parser

        self.assertEqual(result["sources"], 1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(raw_news["url"], "https://example.com/news/1")
        self.assertEqual(raw_news["title"], "Fake news")
        self.assertEqual(raw_news["text"], "Fake text")
        self.assertEqual(raw_news["status"], "new")
        self.assertIsNotNone(source["last_parsed_at"])

    def test_parser_skips_duplicate_news_url(self):
        original_parser = parser_module.NewsParser
        parser_module.NewsParser = FakeNewsParser
        try:
            with connect_db(TEST_DB_PATH) as db:
                db.execute("""
                    INSERT INTO sources (name, url)
                    VALUES (?, ?)
                """, ("Fake Source", "https://example.com"))
                db.commit()

            first = parser_module.run_parser_from_db(TEST_DB_PATH)
            second = parser_module.run_parser_from_db(TEST_DB_PATH)

            with connect_db(TEST_DB_PATH) as db:
                count = db.execute("SELECT COUNT(*) AS count FROM raw_news").fetchone()["count"]
        finally:
            parser_module.NewsParser = original_parser

        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(count, 1)

    def test_parser_continues_after_old_article(self):
        parser = parser_module.NewsParser("https://example.com", pause=0)
        parser._fetch_page = fake_fetch_page
        parser._process_article = fake_process_article

        result = parser.parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://example.com/new")


class FakeNewsParser:
    def __init__(self, **_kwargs):
        pass

    def parse(self):
        return [{
            "url": "https://example.com/news/1",
            "title": "Fake news",
            "published_at": "2026-04-30 10:00:00",
            "text": "Fake text",
        }]


def fake_fetch_page(_url):
    return parser_module.BeautifulSoup("""
        <html>
            <a class="g-inline-text-badges js-item-link" href="/old">Old</a>
            <a class="g-inline-text-badges js-item-link" href="/new">New</a>
        </html>
    """, "lxml")


def fake_process_article(article_url, title):
    if title == "Old":
        return False
    return {
        "url": article_url,
        "title": title,
        "published_at": "2026-04-30 10:00:00",
        "text": "New text",
    }


if __name__ == "__main__":
    unittest.main()
