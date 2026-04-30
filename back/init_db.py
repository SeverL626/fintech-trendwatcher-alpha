import os
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "app.db"
DB_PATH = Path(os.getenv("DB_PATH", DEFAULT_DB_PATH))


INITIAL_SOURCE = {
    "id": 1,
    "name": "RBC Trends Fintech",
    "url": "https://trends.rbc.ru/trends/tag/fintech",
    "source_type": "site",
    "is_active": 1,
    "parse_frequency_minutes": 60,
    "parser_config": {
        "max_age_days": 2,
        "link_selector": "a.g-inline-text-badges.js-item-link",
        "date_selectors": None,
        "text_selector": "article p",
        "pause": 0.5,
        "timeout": 15,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "use_fallback_date_search": True,
        "date_formats": None,
    },
}


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
            seed_source(connection)
        connection.commit()


def ensure_column(connection: sqlite3.Connection, table_name: str, column_name: str, column_type: str) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name not in columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def seed_source(connection: sqlite3.Connection) -> None:
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
        INITIAL_SOURCE["id"],
        INITIAL_SOURCE["name"],
        INITIAL_SOURCE["url"],
        INITIAL_SOURCE["source_type"],
        INITIAL_SOURCE["is_active"],
        INITIAL_SOURCE["parse_frequency_minutes"],
        json.dumps(INITIAL_SOURCE["parser_config"], ensure_ascii=False),
    ))


if __name__ == "__main__":
    init_db()
