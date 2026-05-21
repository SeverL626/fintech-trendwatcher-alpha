import os
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
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
SIGNAL_CATEGORIES = (
    "Регулирование и комплаенс",
    "Платежи и инфраструктура",
    "Антифрод и кибербезопасность",
    "Банковские продукты и клиентский опыт",
    "Конкуренты и банковский рынок",
    "Финтех и новые технологии",
    "Идентификация и биометрия",
    "Санкции и ограничения",
    "Макроэкономика и ставки",
    "Рынки и инвестиции",
    "Финансовые результаты и отчетность",
    "Статистика и данные",
)
INITIAL_SOURCES = [
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
        "url": "https://iss.moex.com/iss/engines/stock/markets/shares/securities.json?iss.meta=off&iss.only=securities,marketdata",
        "source_type": "api",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "moex",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 500,
            "page_size": 100,
            "paginate": True,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
            "headers": {"Accept": "application/json"},
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
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
            "max_age_hours": 24,
            "min_text_length": 20,
            "timeout": 15,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 24,
        "name": "Росфинмониторинг: информационные сообщения",
        "url": "https://fedsfm.ru/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "fedsfm",
            "max_age_days": PARSE_WINDOW_DAYS,
            "link_selector": "a[href^='/news/']",
            "url_contains": ["/news/"],
            "text_selector": "p",
            "require_date": True,
            "prefer_listing_title": True,
            "max_links": 30,
            "timeout": 20,
            "verify_ssl": False,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 25,
        "name": "ФНС России: новости",
        "url": "https://www.nalog.gov.ru/rn77/news/activities_fts/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "nalog",
            "max_age_days": PARSE_WINDOW_DAYS,
            "link_selector": "a[href*='/news/activities_fts/']",
            "url_contains": ["/news/activities_fts/"],
            "text_selector": ".content p, main p, p",
            "require_date": True,
            "max_links": 40,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 26,
        "name": "Банк России: новости",
        "url": "https://cbr.ru/news/",
        "source_type": "api",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "cbr_news",
            "max_age_days": PARSE_WINDOW_DAYS,
            "endpoint": "https://cbr.ru/news/new_ent/",
            "page_size": 50,
            "max_links": 50,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 27,
        "name": "Ассоциация ФинТех: пресс-центр",
        "url": "https://www.fintechru.org/press-center/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "html",
            "max_age_days": PARSE_WINDOW_DAYS,
            "link_selector": "a[href*='/press-center/news/'], a[href*='/press-center/digest/']",
            "url_contains": ["/press-center/news/", "/press-center/digest/"],
            "text_selector": "article p, .content p, main p, p",
            "require_date": True,
            "max_links": 30,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 28,
        "name": "Fintech News Singapore RSS",
        "url": "https://fintechnews.sg/feed/",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 29,
        "name": "The Paypers: fintech and payments",
        "url": "https://thepaypers.com/",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "html",
            "max_age_days": PARSE_WINDOW_DAYS,
            "link_selector": "a[href*='/news/']",
            "url_contains": ["/news/"],
            "text_selector": "article p, main p, p",
            "require_date": True,
            "max_links": 40,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 30,
        "name": "IBS Intelligence RSS",
        "url": "https://ibsintelligence.com/feed/",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 31,
        "name": "TechAfrica News RSS",
        "url": "https://techafricanews.com/feed/",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 32,
        "name": "Biometric Update RSS",
        "url": "https://www.biometricupdate.com/feed",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 33,
        "name": "Cloud Computing News RSS",
        "url": "https://www.cloudcomputing-news.net/feed/",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 34,
        "name": "GlobeNewswire: public companies",
        "url": "https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 30,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 35,
        "name": "ECB: press releases RSS",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 36,
        "name": "Korea Herald: business",
        "url": "https://www.koreaherald.com/business",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "koreaherald",
            "max_age_days": PARSE_WINDOW_DAYS,
            "link_selector": "a[href*='/article/']",
            "url_contains": ["/article/"],
            "text_selector": "article p, .article_view p, #articleText p, main p",
            "require_date": True,
            "max_links": 30,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 37,
        "name": "The Fintech Times RSS",
        "url": "https://thefintechtimes.com/feed/",
        "source_type": "rss",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "rss",
            "max_age_days": PARSE_WINDOW_DAYS,
            "max_items": 20,
            "fetch_article_text": False,
            "timeout": 20,
            "user_agent": DEFAULT_USER_AGENT,
        },
    },
    {
        "id": 39,
        "name": "Deloitte Insights",
        "url": "https://www.deloitte.com/us/en/insights.html",
        "source_type": "site",
        "is_active": 1,
        "parse_frequency_minutes": 60,
        "parser_config": {
            "connector": "deloitte_insights",
            "max_age_days": 31,
            "max_age_hours": 744,
            "link_selector": "a[href*='/us/en/insights/']",
            "url_contains": ["/us/en/insights/"],
            "text_selector": "article p, main p, [data-component-name] p, p",
            "require_date": True,
            "strict_dates": True,
            "max_links": 100,
            "search_page_size": 100,
            "search_max_pages": 3,
            "timeout": 20,
            "allow_javascript_placeholder": True,
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

-- MOEX daily market context snapshot. This is a snapshot by selected instruments,
-- not full official statistics of every MOEX trade.
CREATE TABLE IF NOT EXISTS moex_daily_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL DEFAULT 4,
    trade_date TEXT NOT NULL,
    securities_count INTEGER,
    instruments_count INTEGER,
    traded_securities_count INTEGER,
    traded_instruments_count INTEGER,
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

-- Per-instrument MOEX daily marketdata rows.
CREATE TABLE IF NOT EXISTS moex_instruments_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    secid TEXT NOT NULL,
    boardid TEXT,
    shortname TEXT,
    secname TEXT,
    last REAL,
    open REAL,
    high REAL,
    low REAL,
    marketprice REAL,
    value_rub REAL,
    value_usd REAL,
    volume REAL,
    numtrades INTEGER,
    change_percent REAL,
    raw_data TEXT,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(trade_date, secid, boardid)
);

-- Rule-based market anomalies created from moex_instruments_daily.
CREATE TABLE IF NOT EXISTS market_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity INTEGER NOT NULL CHECK(severity BETWEEN 1 AND 5),
    title TEXT NOT NULL,
    description TEXT,
    related_tickers TEXT,
    metrics_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(event_date, event_type, title)
);

CREATE TABLE IF NOT EXISTS moex_fetch_status (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_fetch_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_raw_news_status ON raw_news(status);
CREATE INDEX IF NOT EXISTS idx_raw_news_content_hash ON raw_news(content_hash);
CREATE INDEX IF NOT EXISTS idx_raw_news_source_id ON raw_news(source_id);
CREATE INDEX IF NOT EXISTS idx_moex_daily_stats_trade_date ON moex_daily_stats(trade_date);
CREATE INDEX IF NOT EXISTS idx_moex_instruments_daily_trade_date ON moex_instruments_daily(trade_date);
CREATE INDEX IF NOT EXISTS idx_moex_instruments_daily_secid ON moex_instruments_daily(secid);
CREATE INDEX IF NOT EXISTS idx_moex_instruments_daily_secid_date ON moex_instruments_daily(secid, trade_date);
CREATE INDEX IF NOT EXISTS idx_moex_instruments_daily_date_value ON moex_instruments_daily(trade_date, value_rub);
CREATE INDEX IF NOT EXISTS idx_moex_instruments_daily_date_trades ON moex_instruments_daily(trade_date, numtrades);
CREATE INDEX IF NOT EXISTS idx_moex_instruments_daily_date_change ON moex_instruments_daily(trade_date, change_percent);
CREATE INDEX IF NOT EXISTS idx_market_events_date ON market_events(event_date);
CREATE INDEX IF NOT EXISTS idx_market_events_type ON market_events(event_type);
"""


def build_signals_schema_sql() -> str:
    category_values = ",\n        ".join(f"'{category}'" for category in SIGNAL_CATEGORIES)
    return f"""
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    headline TEXT NOT NULL,
    hotness INTEGER NOT NULL CHECK(hotness BETWEEN 1 AND 5),
    why_now TEXT,
    category TEXT NOT NULL CHECK(category IN (
        {category_values}
    )),
    sources TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    draft TEXT
);
"""


SIGNALS_SCHEMA_SQL = build_signals_schema_sql()


def get_db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path) if db_path is not None else DB_PATH


@contextmanager
def connect_db(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    path = get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connection
    finally:
        connection.close()


def init_db(db_path: str | Path | None = None, seed_initial_source: bool = True) -> None:
    with connect_db(db_path) as connection:
        connection.executescript(SCHEMA_SQL)
        ensure_column(connection, "sources", "parser_config", "TEXT")
        ensure_moex_daily_columns(connection)
        ensure_moex_fetch_status(connection)
        ensure_signals_schema(connection)
        remove_retired_sources(connection)
        cleanup_bad_raw_news(connection)
        cleanup_orphan_signals(connection)
        cleanup_duplicate_signal_sources(connection)
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
        "instruments_count": "INTEGER",
        "traded_instruments_count": "INTEGER",
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

    connection.execute("""
        UPDATE moex_daily_stats
        SET instruments_count = COALESCE(instruments_count, securities_count),
            traded_instruments_count = COALESCE(traded_instruments_count, traded_securities_count)
    """)


def ensure_moex_fetch_status(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT id FROM moex_fetch_status WHERE id = 1").fetchone()
    if not row:
        connection.execute("INSERT INTO moex_fetch_status (id) VALUES (1)")


def ensure_signals_schema(connection: sqlite3.Connection) -> None:
    desired_columns = [
        "id",
        "headline",
        "hotness",
        "why_now",
        "category",
        "sources",
        "summary",
        "draft",
    ]
    columns = [
        row["name"]
        for row in connection.execute("PRAGMA table_info(signals)")
    ]
    schema_row = connection.execute("""
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'signals'
    """).fetchone()
    schema_sql = schema_row["sql"] if schema_row else ""
    if not columns:
        connection.execute(SIGNALS_SCHEMA_SQL)
        return
    has_expected_constraints = (
        "CHECK(hotness BETWEEN 1 AND 5)" in schema_sql
        and "sources TEXT NOT NULL DEFAULT '[]'" in schema_sql
        and schema_has_current_signal_categories(schema_sql)
    )
    if columns == desired_columns and has_expected_constraints:
        return

    backup_name = f"signals_legacy_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    connection.execute(f"ALTER TABLE signals RENAME TO {backup_name}")
    connection.execute(SIGNALS_SCHEMA_SQL)
    if all(column in columns for column in desired_columns):
        migrate_legacy_signals(connection, backup_name)


def schema_has_current_signal_categories(schema_sql: str) -> bool:
    return all(f"'{category}'" in schema_sql for category in SIGNAL_CATEGORIES)


def migrate_legacy_signals(connection: sqlite3.Connection, backup_name: str) -> None:
    connection.execute(f"""
        INSERT INTO signals (
            id,
            headline,
            hotness,
            why_now,
            category,
            sources,
            summary,
            draft
        )
        SELECT
            id,
            headline,
            hotness,
            why_now,
            CASE category
                WHEN 'Инвестиции и рынки' THEN 'Рынки и инвестиции'
                WHEN 'Корпоративные финансы и сделки' THEN 'Рынки и инвестиции'
                WHEN 'Финансовые результаты' THEN 'Финансовые результаты и отчетность'
                WHEN 'Макроэкономика и статистика' THEN 'Макроэкономика и ставки'
                ELSE 'Регулирование и комплаенс'
            END,
            sources,
            summary,
            draft
        FROM {backup_name}
    """)


def remove_retired_sources(connection: sqlite3.Connection) -> None:
    connection.execute("""
        DELETE FROM sources
        WHERE url = 'https://searchapi.api.cloud.yandex.net/v2/web/searchAsync'
           OR url LIKE 'https://www.finextra.com/rss/%'
           OR url = 'https://www.finextra.com/research'
           OR url = 'https://www.cbr.ru/rss/eventrss'
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


def cleanup_orphan_signals(connection: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(signals)")
    }
    if "sources" not in columns:
        return

    existing_raw_news_ids = {
        row["id"]
        for row in connection.execute("SELECT id FROM raw_news")
    }
    rows = connection.execute("SELECT id, sources FROM signals").fetchall()
    for row in rows:
        source_ids = parse_signal_source_ids(row["sources"])
        kept_ids = [source_id for source_id in source_ids if source_id in existing_raw_news_ids]
        if not kept_ids:
            connection.execute("DELETE FROM signals WHERE id = ?", (row["id"],))
        elif kept_ids != source_ids:
            connection.execute(
                "UPDATE signals SET sources = ? WHERE id = ?",
                (serialize_signal_source_ids(kept_ids), row["id"]),
            )


def cleanup_duplicate_signal_sources(connection: sqlite3.Connection) -> None:
    rows = connection.execute("SELECT id, sources, draft FROM signals").fetchall()
    signals_by_single_source = {}
    for row in rows:
        source_ids = parse_signal_source_ids(row["sources"])
        if len(source_ids) != 1:
            continue
        signals_by_single_source.setdefault(source_ids[0], []).append(row)

    for duplicate_rows in signals_by_single_source.values():
        if len(duplicate_rows) < 2:
            continue
        keeper = sorted(
            duplicate_rows,
            key=lambda row: (
                is_duplicate_signal_draft(row["draft"]),
                row["id"],
            ),
        )[0]
        for row in duplicate_rows:
            if row["id"] != keeper["id"]:
                connection.execute("DELETE FROM signals WHERE id = ?", (row["id"],))


def is_duplicate_signal_draft(value) -> bool:
    return str(value or "").startswith("DUBLICATE OF ")


def parse_signal_source_ids(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, int):
        return [value]

    text = str(value).strip()
    if not text:
        return []
    if re.fullmatch(r"\d+", text):
        return [int(text)]
    if "," in text and not text.startswith("["):
        return [int(part) for part in re.findall(r"\d+", text)]

    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return [int(part) for part in re.findall(r"\d+", text)]

    if isinstance(parsed, int):
        return [parsed]
    if isinstance(parsed, list):
        result = []
        for item in parsed:
            try:
                result.append(int(item))
            except (TypeError, ValueError):
                continue
        return result
    return []


def serialize_signal_source_ids(source_ids: list[int]) -> str:
    source_ids = sorted(set(source_ids))
    if len(source_ids) == 1:
        return str(source_ids[0])
    return ",".join(str(source_id) for source_id in source_ids)


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

# ==============================
# MOEX market context helpers
# ==============================

MOEX_WATCHLIST = {
    "SBER",
    "VTBR",
    "MOEX",
    "TCSG",
    "GAZP",
    "LKOH",
    "ROSN",
}


def update_moex_fetch_status(
    connection: sqlite3.Connection,
    *,
    success: bool,
    error: str | None = None,
) -> None:
    ensure_moex_fetch_status(connection)
    now = datetime.now().isoformat(timespec="seconds")
    if success:
        connection.execute("""
            UPDATE moex_fetch_status
            SET last_fetch_at = ?,
                last_success_at = ?,
                last_error = NULL,
                updated_at = ?
            WHERE id = 1
        """, (now, now, now))
        return

    connection.execute("""
        UPDATE moex_fetch_status
        SET last_fetch_at = ?,
            last_error = ?,
            updated_at = ?
        WHERE id = 1
    """, (now, error, now))


def insert_moex_instrument_daily(
    connection: sqlite3.Connection,
    trade_date: str,
    secid: str,
    boardid: str | None = None,
    shortname: str | None = None,
    secname: str | None = None,
    last: float | None = None,
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
    marketprice: float | None = None,
    value_rub: float | None = None,
    value_usd: float | None = None,
    volume: float | None = None,
    numtrades: int | None = None,
    change_percent: float | None = None,
    raw_data: dict | None = None,
) -> bool:
    if not trade_date or not secid:
        return False

    # SQLite UNIQUE permits multiple NULL values, so normalize missing boardid
    # to an empty string before ON CONFLICT(trade_date, secid, boardid).
    boardid = boardid or ""
    raw_data_json = json.dumps(raw_data or {}, ensure_ascii=False) if raw_data is not None else None
    before = connection.total_changes
    connection.execute("""
        INSERT INTO moex_instruments_daily (
            trade_date,
            secid,
            boardid,
            shortname,
            secname,
            last,
            open,
            high,
            low,
            marketprice,
            value_rub,
            value_usd,
            volume,
            numtrades,
            change_percent,
            raw_data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, secid, boardid) DO UPDATE SET
            shortname = excluded.shortname,
            secname = excluded.secname,
            last = excluded.last,
            open = excluded.open,
            high = excluded.high,
            low = excluded.low,
            marketprice = excluded.marketprice,
            value_rub = excluded.value_rub,
            value_usd = excluded.value_usd,
            volume = excluded.volume,
            numtrades = excluded.numtrades,
            change_percent = excluded.change_percent,
            raw_data = excluded.raw_data,
            fetched_at = CURRENT_TIMESTAMP
    """, (
        trade_date,
        secid,
        boardid,
        shortname,
        secname,
        last,
        open_price,
        high,
        low,
        marketprice,
        value_rub,
        value_usd,
        volume,
        numtrades,
        change_percent,
        raw_data_json,
    ))
    return connection.total_changes > before


def insert_moex_daily_stat(
    connection: sqlite3.Connection,
    source_id_or_trade_date,
    stat: dict | None = None,
) -> bool:
    """
    Conflict-safe upsert for daily MOEX snapshot in the SAME app.db.

    Supports both call styles during refactor:
    - insert_moex_daily_stat(connection, source_id, stat)
    - insert_moex_daily_stat(connection, trade_date, stat)
    """
    if stat is None:
        return False

    if isinstance(source_id_or_trade_date, str) and not source_id_or_trade_date.isdigit():
        source_id = int(stat.get("source_id") or 4)
        trade_date = source_id_or_trade_date
    else:
        source_id = int(source_id_or_trade_date or stat.get("source_id") or 4)
        trade_date = stat.get("trade_date")

    if not trade_date:
        return False

    securities_count = stat.get("securities_count") or stat.get("instruments_count")
    instruments_count = stat.get("instruments_count") or stat.get("securities_count")
    traded_securities_count = stat.get("traded_securities_count") or stat.get("traded_instruments_count")
    traded_instruments_count = stat.get("traded_instruments_count") or stat.get("traded_securities_count")
    raw_data_json = json.dumps(stat.get("raw_data") or {}, ensure_ascii=False)

    before = connection.total_changes
    connection.execute("""
        INSERT INTO moex_daily_stats (
            source_id,
            trade_date,
            securities_count,
            instruments_count,
            traded_securities_count,
            traded_instruments_count,
            total_value,
            total_value_usd,
            total_volume,
            total_trades,
            average_last,
            average_marketprice,
            top_secid,
            top_shortname,
            top_value,
            top_volume_secid,
            top_volume_shortname,
            top_volume,
            top_trades_secid,
            top_trades_shortname,
            top_trades,
            moex_systime,
            raw_data
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, trade_date) DO UPDATE SET
            securities_count = excluded.securities_count,
            instruments_count = excluded.instruments_count,
            traded_securities_count = excluded.traded_securities_count,
            traded_instruments_count = excluded.traded_instruments_count,
            total_value = excluded.total_value,
            total_value_usd = excluded.total_value_usd,
            total_volume = excluded.total_volume,
            total_trades = excluded.total_trades,
            average_last = excluded.average_last,
            average_marketprice = excluded.average_marketprice,
            top_secid = excluded.top_secid,
            top_shortname = excluded.top_shortname,
            top_value = excluded.top_value,
            top_volume_secid = excluded.top_volume_secid,
            top_volume_shortname = excluded.top_volume_shortname,
            top_volume = excluded.top_volume,
            top_trades_secid = excluded.top_trades_secid,
            top_trades_shortname = excluded.top_trades_shortname,
            top_trades = excluded.top_trades,
            moex_systime = excluded.moex_systime,
            raw_data = excluded.raw_data,
            fetched_at = CURRENT_TIMESTAMP
    """, (
        source_id,
        trade_date,
        securities_count,
        instruments_count,
        traded_securities_count,
        traded_instruments_count,
        stat.get("total_value"),
        stat.get("total_value_usd"),
        stat.get("total_volume"),
        stat.get("total_trades"),
        stat.get("average_last"),
        stat.get("average_marketprice"),
        stat.get("top_secid"),
        stat.get("top_shortname"),
        stat.get("top_value"),
        stat.get("top_volume_secid"),
        stat.get("top_volume_shortname"),
        stat.get("top_volume"),
        stat.get("top_trades_secid"),
        stat.get("top_trades_shortname"),
        stat.get("top_trades"),
        stat.get("moex_systime"),
        raw_data_json,
    ))
    return connection.total_changes > before


def insert_market_event(
    connection: sqlite3.Connection,
    event_date: str | dict,
    event_type: str | None = None,
    severity: int | None = None,
    title: str | None = None,
    description: str | None = None,
    related_tickers: list[str] | None = None,
    metrics: dict | None = None,
) -> bool:
    if isinstance(event_date, dict):
        event = event_date
        event_date = event.get("event_date")
        event_type = event.get("event_type")
        severity = event.get("severity")
        title = event.get("title")
        description = event.get("description")
        related_tickers = event.get("related_tickers")
        metrics = event.get("metrics")

    if not event_date or not event_type or not title:
        return False

    tickers_json = json.dumps(related_tickers or [], ensure_ascii=False)
    metrics_json = json.dumps(metrics or {}, ensure_ascii=False)
    before = connection.total_changes
    connection.execute("""
        INSERT INTO market_events (
            event_date,
            event_type,
            severity,
            title,
            description,
            related_tickers,
            metrics_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_date, event_type, title) DO UPDATE SET
            severity = excluded.severity,
            description = excluded.description,
            related_tickers = excluded.related_tickers,
            metrics_json = excluded.metrics_json,
            created_at = CURRENT_TIMESTAMP
    """, (
        event_date,
        event_type,
        int(severity or 1),
        title,
        description,
        tickers_json,
        metrics_json,
    ))
    return connection.total_changes > before


def median(values: list[float]) -> float | None:
    clean_values = sorted(float(value) for value in values if value is not None)
    if not clean_values:
        return None

    count = len(clean_values)
    middle = count // 2
    if count % 2:
        return clean_values[middle]
    return (clean_values[middle - 1] + clean_values[middle]) / 2


def get_recent_values(
    connection: sqlite3.Connection,
    secid: str,
    column_name: str,
    before_date: str,
    days: int = 30,
) -> list[float]:
    if column_name not in {"value_rub", "numtrades", "volume", "change_percent"}:
        raise ValueError(f"Unsupported MOEX history column: {column_name}")

    rows = connection.execute(f"""
        SELECT {column_name} AS value
        FROM moex_instruments_daily
        WHERE secid = ?
          AND trade_date < ?
          AND {column_name} IS NOT NULL
        ORDER BY date(trade_date) DESC
        LIMIT ?
    """, (secid, before_date, days)).fetchall()

    result = []
    for row in rows:
        try:
            result.append(float(row["value"]))
        except (TypeError, ValueError):
            continue
    return result


def detect_market_anomalies(
    connection: sqlite3.Connection,
    trade_date: str,
) -> list[dict]:
    """
    Rule-based anomaly detector for MOEX market context.

    It compares today's instrument values with the real median of previous 30 trading
    days. It does not use ML/LLM and does not create raw_news.
    """
    if not trade_date:
        return []

    rows = connection.execute("""
        SELECT secid, shortname, value_rub, numtrades, change_percent
        FROM moex_instruments_daily
        WHERE trade_date = ?
          AND (value_rub IS NOT NULL OR numtrades IS NOT NULL OR change_percent IS NOT NULL)
    """, (trade_date,)).fetchall()

    events = []
    for row in rows:
        secid = row["secid"]
        shortname = row["shortname"] or secid
        value_today = row["value_rub"]
        trades_today = row["numtrades"]
        change_percent = row["change_percent"]

        value_history = get_recent_values(connection, secid, "value_rub", trade_date, 30)
        trades_history = get_recent_values(connection, secid, "numtrades", trade_date, 30)

        median_value = median(value_history) if len(value_history) >= 5 else None
        median_trades = median(trades_history) if len(trades_history) >= 5 else None
        base_severity = 3 if secid in MOEX_WATCHLIST else 2

        if value_today is not None and median_value and median_value > 0:
            value_ratio = float(value_today) / float(median_value)
            if value_ratio >= 3.0:
                events.append({
                    "event_date": trade_date,
                    "event_type": "turnover_spike",
                    "severity": base_severity,
                    "title": f"Всплеск оборота: {shortname}",
                    "description": f"Оборот {shortname} в {value_ratio:.1f} раза выше медианы последних 30 торговых дней.",
                    "related_tickers": [secid],
                    "metrics": {
                        "value_ratio": round(value_ratio, 2),
                        "value_today": value_today,
                        "median_value_30d": median_value,
                    },
                })

        if trades_today is not None and median_trades and median_trades > 0:
            trades_ratio = float(trades_today) / float(median_trades)
            if trades_ratio >= 3.0:
                events.append({
                    "event_date": trade_date,
                    "event_type": "trades_spike",
                    "severity": base_severity,
                    "title": f"Всплеск сделок: {shortname}",
                    "description": f"Сделок по {shortname} в {trades_ratio:.1f} раза больше медианы последних 30 торговых дней.",
                    "related_tickers": [secid],
                    "metrics": {
                        "trades_ratio": round(trades_ratio, 2),
                        "trades_today": trades_today,
                        "median_trades_30d": median_trades,
                    },
                })

        if change_percent is not None:
            change_percent = float(change_percent)
            if abs(change_percent) >= 3.0:
                events.append({
                    "event_date": trade_date,
                    "event_type": "price_move",
                    "severity": base_severity,
                    "title": f"Значительное движение цены: {shortname}",
                    "description": f"Цена {shortname} изменилась на {change_percent:+.1f}%.",
                    "related_tickers": [secid],
                    "metrics": {
                        "change_percent": round(change_percent, 2),
                    },
                })

    return events


def get_latest_market_snapshot(connection: sqlite3.Connection) -> dict | None:
    row = connection.execute("""
        SELECT *
        FROM moex_daily_stats
        ORDER BY date(trade_date) DESC, id DESC
        LIMIT 1
    """).fetchone()
    return dict(row) if row else None


def get_market_events(
    connection: sqlite3.Connection,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    rows = connection.execute("""
        SELECT *
        FROM market_events
        ORDER BY severity DESC, date(event_date) DESC, id DESC
        LIMIT ? OFFSET ?
    """, (max(1, int(limit or 50)), max(0, int(offset or 0)))).fetchall()

    result = []
    for row in rows:
        event = dict(row)
        try:
            event["related_tickers"] = json.loads(event.get("related_tickers") or "[]")
        except json.JSONDecodeError:
            event["related_tickers"] = []
        try:
            event["metrics"] = json.loads(event.get("metrics_json") or "{}")
        except json.JSONDecodeError:
            event["metrics"] = {}
        result.append(event)
    return result


if __name__ == "__main__":
    init_db()
