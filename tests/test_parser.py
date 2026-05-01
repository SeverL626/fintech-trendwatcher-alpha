import json
import sys
import unittest
from datetime import datetime
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
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["empty_sources"], 0)
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
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(count, 1)

    def test_parser_continues_after_old_article(self):
        parser = parser_module.NewsParser("https://example.com", pause=0)
        parser._fetch_page = fake_fetch_page
        parser._process_article = fake_process_article

        result = parser.parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://example.com/new")

    def test_parser_can_run_single_source_by_id(self):
        original_parser = parser_module.NewsParser
        parser_module.NewsParser = FakeNewsParser
        try:
            with connect_db(TEST_DB_PATH) as db:
                db.execute("""
                    INSERT INTO sources (name, url)
                    VALUES (?, ?)
                """, ("Fake Source", "https://example.com"))
                db.execute("""
                    INSERT INTO sources (name, url)
                    VALUES (?, ?)
                """, ("Other Source", "https://other.example.com"))
                db.commit()

            result = parser_module.run_parser_for_source_id(TEST_DB_PATH, 1)

            with connect_db(TEST_DB_PATH) as db:
                count = db.execute("SELECT COUNT(*) AS count FROM raw_news").fetchone()["count"]
        finally:
            parser_module.NewsParser = original_parser

        self.assertEqual(result["sources"], 1)
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["duplicates"], 0)
        self.assertEqual(count, 1)
        self.assertIn("Fake Source", result["summary"][0])

    def test_parser_reports_source_errors_with_url_and_kind(self):
        original_parser = parser_module.NewsParser

        class BrokenNewsParser:
            def __init__(self, **_kwargs):
                pass

            def parse(self):
                raise RuntimeError("boom")

        parser_module.NewsParser = BrokenNewsParser
        try:
            with connect_db(TEST_DB_PATH) as db:
                db.execute("""
                    INSERT INTO sources (name, url, parser_config)
                    VALUES (?, ?, ?)
                """, (
                    "Broken Source",
                    "https://broken.example.com",
                    json.dumps({"kind": "html"}),
                ))
                db.commit()

            result = parser_module.run_parser_from_db(TEST_DB_PATH)
        finally:
            parser_module.NewsParser = original_parser

        self.assertEqual(result["created"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["empty_sources"], 0)
        self.assertEqual(result["results"][0]["source_url"], "https://broken.example.com")
        self.assertEqual(result["results"][0]["kind"], "html")
        self.assertIn("ошибка", result["summary"][0])

    def test_rss_adapter_returns_recent_items(self):
        original_fetch_response = parser_module.fetch_response
        parser_module.fetch_response = lambda _url, _config: FakeResponse(f"""
            <rss><channel>
                <item>
                    <title>Recent RSS item</title>
                    <link>https://example.com/rss/1</link>
                    <pubDate>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</pubDate>
                    <description><![CDATA[<p>RSS text</p>]]></description>
                </item>
            </channel></rss>
        """)
        try:
            items = parser_module.parse_xml_feed(
                "https://example.com/rss",
                "RSS Source",
                {"max_age_days": 3, "user_agent": "test"},
            )
        finally:
            parser_module.fetch_response = original_fetch_response

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Recent RSS item")
        self.assertEqual(items[0]["text"], "RSS text")

    def test_json_adapter_reads_moex_table_shape(self):
        original_fetch_response = parser_module.fetch_response
        parser_module.fetch_response = lambda _url, _config: FakeJsonResponse({
            "securities": {
                "columns": ["SECID", "SECNAME"],
                "data": [["SBER", "Сбербанк"]],
            }
        })
        try:
            items = parser_module.parse_json_endpoint(
                "https://iss.moex.com/example.json",
                "MOEX",
                {"max_items": 10},
            )
        finally:
            parser_module.fetch_response = original_fetch_response

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Сбербанк")
        self.assertIn("SBER", items[0]["text"])


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


class FakeResponse:
    def __init__(self, text):
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {}


class FakeJsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


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
