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
PARSE_WINDOW_DAYS = 1
PARSE_WINDOW_HOURS = 24
RAW_NEWS_RETENTION_DAYS = 7
MAX_FUTURE_HOURS = 2
MIN_TEXT_LENGTH = 80
INITIAL_SOURCES = [
    {
        "id": 1,
        "name": "Банк России: новости, интервью, выступления",
        "url": "https://www.cbr.ru/rss/eventrss",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "cbr",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "minfin",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "rosstat",
            "max_age_days": PARSE_WINDOW_DAYS,
            "file_extensions": [".xls", ".xlsx", ".csv", ".zip", ".pdf", ".doc", ".docx"],
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
            "connector": "moex",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "alfabank",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "sber",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "tbank",
            "max_age_days": PARSE_WINDOW_DAYS,
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
        "url": "https://www.vtb.ru/about/press/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "vtb",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "rbc",
            "max_age_days": PARSE_WINDOW_DAYS,
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
            "connector": "vedomosti",
            "max_age_days": PARSE_WINDOW_DAYS,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 11,
        "name": "Коммерсантъ: финансы",
        "url": "https://www.kommersant.ru/finance",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "kommersant",
            "max_age_days": PARSE_WINDOW_DAYS,
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
        "name": "Telegram: Банк России",
        "url": "https://t.me/centralbank_russia",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "centralbank_russia",
            "source_reliability": "official",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 13,
        "name": "Telegram: Минфин России",
        "url": "https://t.me/minfin",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "minfin",
            "source_reliability": "official",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 14,
        "name": "Telegram: Frank Media",
        "url": "https://t.me/frank_media",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "frank_media",
            "source_reliability": "official_media",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 15,
        "name": "Telegram: РБК",
        "url": "https://t.me/rbc_news",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "rbc_news",
            "source_reliability": "official_media",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 16,
        "name": "Telegram: Ведомости",
        "url": "https://t.me/vedomosti",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "vedomosti",
            "source_reliability": "official_media",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 17,
        "name": "Telegram: Коммерсантъ",
        "url": "https://t.me/kommersant",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "kommersant",
            "source_reliability": "official_media",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 18,
        "name": "Telegram: Интерфакс",
        "url": "https://t.me/interfaxonline",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "interfaxonline",
            "source_reliability": "official_media",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 19,
        "name": "Telegram: Банкста",
        "url": "https://t.me/banksta",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "banksta",
            "source_reliability": "unofficial_signal",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 20,
        "name": "Telegram: MMI",
        "url": "https://t.me/russianmacro",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "russianmacro",
            "source_reliability": "unofficial_analysis",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 21,
        "name": "Telegram: MarketTwits",
        "url": "https://t.me/markettwits",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "markettwits",
            "source_reliability": "unofficial_signal",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 22,
        "name": "Telegram: РДВ",
        "url": "https://t.me/AK47pfl",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "AK47pfl",
            "source_reliability": "unofficial_investment_ideas",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 23,
        "name": "Telegram: Финсайд",
        "url": "https://t.me/finside",
        "source_type": "telegram",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "telegram",
            "channel": "finside",
            "source_reliability": "unofficial_signal",
            "max_age_hours": 1,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
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

CREATE TABLE IF NOT EXISTS moex_daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    securities_count INTEGER,
    traded_securities_count INTEGER,
    total_value REAL,
    total_value_usd REAL,
    total_volume REAL,
    total_trades INTEGER,
    average_last REAL,
    average_marketprice REAL,
    top_secid TEXT,
    top_shortname TEXT,
    top_value REAL,
    top_volume_secid TEXT,
    top_volume_shortname TEXT,
    top_volume REAL,
    top_trades_secid TEXT,
    top_trades_shortname TEXT,
    top_trades INTEGER,
    moex_systime TEXT,
    raw_data TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE CASCADE,
    UNIQUE(source_id, trade_date)
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
CREATE INDEX IF NOT EXISTS idx_moex_daily_stats_trade_date ON moex_daily_stats(trade_date);
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
        ensure_moex_daily_columns(connection)
        remove_retired_sources(connection)
        cleanup_bad_raw_news(connection)
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


def ensure_moex_daily_columns(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(moex_daily_stats)")
    }
    new_columns = {
        "total_value_usd": "REAL",
        "traded_securities_count": "INTEGER",
        "top_volume_secid": "TEXT",
        "top_volume_shortname": "TEXT",
        "top_volume": "REAL",
        "top_trades_secid": "TEXT",
        "top_trades_shortname": "TEXT",
        "top_trades": "INTEGER",
        "moex_systime": "TEXT",
    }
    for column_name, column_type in new_columns.items():
        if column_name not in columns:
            connection.execute(f"ALTER TABLE moex_daily_stats ADD COLUMN {column_name} {column_type}")


def remove_retired_sources(connection: sqlite3.Connection) -> None:
    connection.execute("""
        DELETE FROM sources
        WHERE url = 'https://searchapi.api.cloud.yandex.net/v2/web/searchAsync'
           OR url LIKE 'https://www.finextra.com/rss/%'
           OR parser_config LIKE '%yandex_search%'
    """)


def cleanup_bad_raw_news(connection: sqlite3.Connection) -> None:
    connection.execute("""
        DELETE FROM raw_news
        WHERE published_at IS NULL
           OR datetime(published_at) < datetime('now', 'localtime', ?)
           OR datetime(published_at) > datetime('now', 'localtime', ?)
           OR LENGTH(TRIM(text)) < ?
           OR TRIM(COALESCE(title, '')) = TRIM(text)
    """, (
        f"-{RAW_NEWS_RETENTION_DAYS} days",
        f"+{MAX_FUTURE_HOURS} hours",
        MIN_TEXT_LENGTH,
    ))
    connection.execute("""
        DELETE FROM raw_news
        WHERE source_id = 2
          AND url NOT LIKE '%id_4=%'
    """)
    connection.execute("""
        DELETE FROM raw_news
        WHERE source_id = 8
          AND (
              url LIKE 'https://www.vtb.com/ir/%'
              OR url = 'https://www.vtb.com/about/press-center/'
              OR url = 'https://www.vtb.ru/about/press/'
          )
    """)
    connection.execute("""
        DELETE FROM raw_news
        WHERE source_id = 7
          AND url = 'https://www.tbank.ru/about/news/'
    """)
    connection.execute("""
        DELETE FROM raw_news
        WHERE source_id = 3
          AND published_at IS NULL
    """)
    connection.execute("""
        DELETE FROM raw_news
        WHERE source_id = 11
          AND raw_data LIKE '%/archive/news%'
    """)


def seed_sources(connection: sqlite3.Connection) -> None:
    for source in INITIAL_SOURCES:
        seed_source(connection, source)


def seed_source(connection: sqlite3.Connection, source: dict) -> None:
    parser_config = dict(source["parser_config"])
    parser_config.setdefault("max_age_days", PARSE_WINDOW_DAYS)
    parser_config.setdefault("max_age_hours", PARSE_WINDOW_HOURS)
    parser_config.setdefault("strict_dates", True)
    parser_config.setdefault("max_future_hours", MAX_FUTURE_HOURS)
    parser_config.setdefault("min_text_length", MIN_TEXT_LENGTH)

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
        json.dumps(parser_config, ensure_ascii=False),
    ))


if __name__ == "__main__":
    init_db()
