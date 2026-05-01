import os
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"
DB_PATH = Path(os.getenv("DB_PATH", DEFAULT_DB_PATH))


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


INITIAL_SOURCES = [
    {
        "id": 1,
        "name": "Банк России: новости",
        "url": "https://www.cbr.ru/scripts/XML_News.asp",
        "source_type": "api",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "xml",
            "max_age_days": 3,
            "item_tags": ["News", "Item", "Record"],
            "title_fields": ["Title", "title", "Name", "name"],
            "url_fields": ["Url", "URL", "Link", "link"],
            "date_fields": ["Date", "date", "DateTime", "pubDate"],
            "text_fields": ["Text", "text", "Description", "description"],
            "url_prefix": "https://www.cbr.ru",
        },
    },
    {
        "id": 2,
        "name": "Минфин России: пресс-центр",
        "url": "https://minfin.gov.ru/ru/press-center/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html",
            "max_age_days": 3,
            "link_selector": "a[href*='press-center'], a[href*='id_4=']",
            "date_selectors": [
                "meta[property='article:published_time']",
                "time[datetime]",
                ".date",
            ],
            "text_selector": "article p, main p",
            "pause": 0.5,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 3,
        "name": "Росстат: национальные счета",
        "url": "https://rosstat.gov.ru/statistics/accounts",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html_files",
            "max_age_days": 3,
            "file_extensions": [".xls", ".xlsx", ".csv", ".zip"],
            "link_selector": "a[href]",
            "url_contains": ["/storage/mediabank/"],
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
            "verify_ssl": False,
        },
    },
    {
        "id": 4,
        "name": "MOEX ISS shares",
        "url": "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json",
        "source_type": "api",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "json",
            "max_age_days": 3,
            "max_items": 50,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 5,
        "name": "Альфа-Банк: новости",
        "url": "https://alfabank.ru/news/t/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html",
            "max_age_days": 3,
            "link_selector": "main a[href*='/news/t/'], a[href*='/news/t/']",
            "date_selectors": [
                "meta[property='article:published_time']",
                "time[datetime]",
                "time",
            ],
            "text_selector": "article p, main p",
            "pause": 0.5,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 6,
        "name": "Сбер: пресс-релизы",
        "url": "https://www.sberbank.com/ru/news-and-media/press-releases",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html_files",
            "max_age_days": 3,
            "link_selector": "a[href]",
            "url_contains": ["/news-and-media/", "/investor-relations/"],
            "file_extensions": [".pdf", ".html"],
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 7,
        "name": "Т-Банк: новости",
        "url": "https://www.tbank.ru/about/news/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html",
            "max_age_days": 3,
            "link_selector": "main a[href*='/about/news/'], a[href*='/about/news/']",
            "date_selectors": [
                "meta[property='article:published_time']",
                "time[datetime]",
                "time",
            ],
            "text_selector": "article p, main p",
            "pause": 0.5,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 8,
        "name": "ВТБ: пресс-центр и IR",
        "url": "https://www.vtb.com/about/press-center/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html_files",
            "max_age_days": 3,
            "link_selector": "a[href]",
            "url_contains": ["/about/press-center/", "/ir/"],
            "file_extensions": [".pdf", ".xlsx", ".xls", ".html"],
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 9,
        "name": "РБК RSS",
        "url": "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "rss",
            "max_age_days": 3,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 10,
        "name": "Ведомости RSS: банки",
        "url": "https://www.vedomosti.ru/rss/rubric/finance/banks",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "rss",
            "max_age_days": 3,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 11,
        "name": "Коммерсантъ: архив новостей",
        "url": "https://www.kommersant.ru/archive/news",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "html",
            "max_age_days": 3,
            "link_selector": "a[href^='/doc/'], a[href*='/doc/']",
            "date_selectors": [
                "meta[property='article:published_time']",
                "time[datetime]",
                "time",
            ],
            "text_selector": "article p, main p",
            "pause": 0.5,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 12,
        "name": "Yandex Search API discovery",
        "url": "https://searchapi.api.cloud.yandex.net/v2/web/searchAsync",
        "source_type": "api",
        "is_active": 0,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "kind": "yandex_search",
            "max_age_days": 3,
            "query_text": "Банк России OR Минфин OR Мосбиржа fintech банк",
            "requires_env": ["YANDEX_API_KEY", "YANDEX_FOLDER_ID"],
        },
    },
]


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'site',
    is_active INTEGER NOT NULL DEFAULT 1,
    parse_frequency_minutes INTEGER NOT NULL DEFAULT 60,
    parser_config TEXT,
    last_parsed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    text TEXT NOT NULL,
    published_at TEXT,
    parsed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'new',
    content_hash TEXT,
    raw_data TEXT,
    error_message TEXT,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_news_id INTEGER NOT NULL,
    headline TEXT NOT NULL,
    hotness INTEGER,
    why_now TEXT,
    category TEXT NOT NULL,
    summary TEXT,
    draft TEXT,
    moderation_status TEXT NOT NULL DEFAULT 'pending',
    confidence REAL,
    model_name TEXT,
    prompt_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (raw_news_id) REFERENCES raw_news(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_raw_news_status ON raw_news(status);
CREATE INDEX IF NOT EXISTS idx_raw_news_content_hash ON raw_news(content_hash);
"""


def get_db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path) if db_path is not None else DB_PATH


@contextmanager
def connect_db(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path | None = None, seed_initial_source: bool = True) -> None:
    with connect_db(db_path) as connection:
        connection.executescript(SCHEMA_SQL)
        ensure_column(connection, "sources", "parser_config", "TEXT")
        if seed_initial_source:
            seed_sources(connection)
        connection.commit()


def ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def seed_sources(connection: sqlite3.Connection) -> None:
    for source in INITIAL_SOURCES:
        seed_source(connection, source)


def seed_source(connection: sqlite3.Connection, source: dict) -> None:
    connection.execute("""
        INSERT INTO sources (
            id,
            name,
            url,
            source_type,
            is_active,
            parse_frequency_minutes,
            parser_config
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            source_type = excluded.source_type,
            is_active = excluded.is_active,
            parse_frequency_minutes = excluded.parse_frequency_minutes,
            parser_config = excluded.parser_config
    """, (
        source["id"],
        source["name"],
        source["url"],
        source["source_type"],
        source["is_active"],
        source["parse_frequency_minutes"],
        json.dumps(source["parser_config"], ensure_ascii=False),
    ))


if __name__ == "__main__":
    init_db()
