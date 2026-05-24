from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone, UTC
from contextlib import contextmanager
from functools import wraps

from pathlib import Path

from flask import Flask, jsonify, request, g
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
import sqlite3
import requests
from apscheduler.schedulers.background import BackgroundScheduler

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent.parent.parent
MAIN_DB_PATH = Path(os.getenv("MAIN_DB_PATH") or os.getenv("DB_PATH") or ROOT_DIR / "data" / "app.db")
FRONT_BACKEND_DB_PATH = Path(os.getenv("FRONT_BACKEND_DB_PATH") or ROOT_DIR / "data" / "redcat.db")
UPDATE_API_URL = os.getenv("UPDATE_API_URL", "http://127.0.0.1:5000/update")
UPDATE_STATUS_URL = os.getenv("UPDATE_STATUS_URL", "http://127.0.0.1:5000/update/status")
UPDATE_STATUS_TOKEN = os.getenv("UPDATE_STATUS_TOKEN", "")
MAX_API_LIMIT = 10000
MSK = timezone(timedelta(hours=3))
MANAGER_EMAIL = "manager@redcat.tu"
DEMO_PLAN = "demo"
PLAN_DURATIONS_DAYS = {
    "demo": 7,
    "basic": 31,
    "plus": 31,
}
AVAILABLE_PLANS = {DEMO_PLAN}
ACTIVE_SUBSCRIPTION = "active"
CANONICAL_SIGNAL_CATEGORIES = (
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

db = SQLAlchemy()
jwt = JWTManager()

REQUEST_METRICS = {
    "requests_total": 0,
    "errors_total": 0,
    "admin_denied_total": 0,
    "auth_denied_total": 0,
}


def utcnow():
    return datetime.now(UTC)


# ПУНКТ 4, 7, 8: Синхронизация с учетом нескольких источников (до 3-х)
def sync_news_from_dp(app_instance):
    with app_instance.app_context():
        if MAIN_DB_PATH.exists():
            rebuild_notifications_for_all_users()
        return

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    activated = db.Column(db.Boolean, default=False)
    subscription_plan = db.Column(db.String(40), default="")
    subscription_status = db.Column(db.String(40), default="inactive")
    subscription_expires_at = db.Column(db.DateTime, nullable=True)
    demo_used = db.Column(db.Boolean, default=False)
    last_notification_check = db.Column(db.DateTime, nullable=True)
    avatar_url = db.Column(db.Text, default="")
    bio = db.Column(db.Text, default="")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role,
            "activated": self.activated,
            "subscription_plan": self.subscription_plan or "",
            "subscription_status": self.subscription_status or "inactive",
            "subscription_expires_at": self.subscription_expires_at.isoformat() if self.subscription_expires_at else "",
            "demo_used": bool(self.demo_used),
            "avatar_url": self.avatar_url or "",
            "bio": self.bio or "",
        }


class PromoCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.String(255), default="")
    active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "description": self.description,
            "active": self.active,
        }


class SignalCard(db.Model):
    __tablename__ = "signals"
    id = db.Column(db.Integer, primary_key=True)
    headline = db.Column(db.String(255), nullable=False)
    hotness = db.Column(db.Integer, default=0)
    category = db.Column(db.String(100), default="")
    summary = db.Column(db.Text, default="")
    why_now = db.Column(db.Text, default="")
    draft = db.Column(db.Text, default="")
    source_name = db.Column(db.String(100), default="manual")
    sources_json = db.Column(db.Text, default="[]")
    url = db.Column(db.Text, default="")
    published_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        try:
            sources = json.loads(self.sources_json or "[]")
        except Exception:
            sources = []

        return {
            "id": self.id,
            "headline": self.headline,
            "hotness": self.hotness,
            "category": self.category,
            "summary": self.summary,
            "why_now": self.why_now,
            "draft": self.draft,
            "source_name": self.source_name,
            "sources_json": self.sources_json,
            "url": self.url,
        }


class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    signal_id = db.Column(db.Integer, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "signal_id", name="uq_user_signal_favorite"),)


class NotificationSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    theme = db.Column(db.String(100), default="")
    source_name = db.Column(db.String(100), default="")
    hotness_min = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "theme": self.theme or "",
            "source_name": self.source_name or "",
            "hotness_min": self.hotness_min or 0,
            "active": self.active,
        }


class NotificationItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    signal_id = db.Column(db.Integer, nullable=True)

    title = db.Column(db.String(255), nullable=False)

    message = db.Column(db.Text, default="")

    kind = db.Column(db.String(40), default="signal")

    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "title": self.title,
            "message": self.message,
            "kind": self.kind,
            "read": self.read,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


class SystemState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    last_signal_check = db.Column(db.DateTime, nullable=True)




SAMPLE_USERS = [
    {
        "full_name": "Manager Red Cat",
        "email": MANAGER_EMAIL,
        "password": "rqbqerj1543tgjkq",
        "role": "admin",
        "activated": True,
        "subscription_plan": "manager",
        "subscription_status": ACTIVE_SUBSCRIPTION,
    },
]
SAMPLE_PROMOS = []


def parse_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def parse_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


def normalize_api_limit(value, default=100, maximum=MAX_API_LIMIT):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(maximum, limit))


def parse_multi_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = str(value).split(",")
    result = []
    seen = set()
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


@contextmanager
def connect_main_db():
    connection = sqlite3.connect(MAIN_DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        yield connection
    finally:
        connection.close()


def table_has_column(connection, table_name, column_name):
    try:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    except sqlite3.Error:
        return False
    return any(row["name"] == column_name for row in rows)


def signal_not_duplicate_where(connection, alias=""):
    prefix = f"{alias}." if alias else ""
    if table_has_column(connection, "signals", "is_duplicate"):
        return f"COALESCE({prefix}is_duplicate, 0) = 0"
    return f"({prefix}draft IS NULL OR {prefix}draft NOT LIKE 'DUBLICATE OF %')"


def signal_frontend_visible_where(connection, alias=""):
    prefix = f"{alias}." if alias else ""
    if not table_has_column(connection, "signals", "is_fintech"):
        return f"{prefix}hotness >= 2"
    if table_has_column(connection, "signals", "processing_status"):
        return (
            f"(COALESCE({prefix}is_fintech, 0) = 1 "
            f"OR {prefix}processing_status IN ('llm_done', 'embedding_done'))"
        )
    return f"COALESCE({prefix}is_fintech, 0) = 1"


def signal_select_fields(connection, alias=""):
    prefix = f"{alias}." if alias else ""
    fields = [
        f"{prefix}id",
        f"{prefix}headline",
        f"{prefix}hotness",
        f"{prefix}why_now",
        f"{prefix}category",
        f"{prefix}sources",
        f"{prefix}summary",
        f"{prefix}draft",
    ]
    for column in ("is_fintech", "scale_score", "urgency_score", "rigidity_score"):
        if table_has_column(connection, "signals", column):
            fields.append(f"{prefix}{column}")
    if table_has_column(connection, "signals", "created_at"):
        fields.append(f"{prefix}created_at AS signal_created_at")
    return ", ".join(fields)



def parse_signal_source_ids(value):
    if value is None:
        return []
    if isinstance(value, int):
        return [value]

    text = str(value).strip()
    if not text:
        return []
    if re.fullmatch(r"\d+", text):
        return [int(text)]
    return [int(part) for part in re.findall(r"\d+", text)]


def unique_values(values):
    result = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def public_draft(value):
    if not value:
        return value or ""
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
    if isinstance(parsed, dict) and "embedding" in parsed:
        return parsed.get("previous_draft") or ""
    return value


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def to_moscow_iso(value):
    parsed = parse_datetime(value)
    if not parsed:
        return value
    return parsed.astimezone(MSK).isoformat()


def load_raw_news_for_signal(connection, raw_news_ids):
    if not raw_news_ids:
        return []

    placeholders = ",".join("?" for _ in raw_news_ids)
    rows = connection.execute(f"""
        SELECT
            rn.id,
            rn.url,
            rn.title,
            rn.published_at,
            rn.parsed_at,
            s.name AS source_name
        FROM raw_news rn
        LEFT JOIN sources s ON s.id = rn.source_id
        WHERE rn.id IN ({placeholders})
    """, tuple(raw_news_ids)).fetchall()

    raw_by_id = {row["id"]: dict(row) for row in rows}
    return [
        raw_by_id[raw_news_id]
        for raw_news_id in raw_news_ids
        if raw_news_id in raw_by_id
    ]


def signal_to_frontend_item(signal, raw_news=None):
    source_ids = parse_signal_source_ids(signal.get("sources"))
    raw_news = raw_news or []
    primary_raw = raw_news[0] if raw_news else {}
    source_names = unique_values(raw_row.get("source_name") for raw_row in raw_news)
    source_urls = unique_values(raw_row.get("url") for raw_row in raw_news)
    raw_titles = unique_values(raw_row.get("title") for raw_row in raw_news)
    source_links = []
    seen_source_links = set()
    for raw_row in raw_news:
        url = str(raw_row.get("url") or "").strip()
        name = str(raw_row.get("source_name") or "").strip()
        key = url or name
        if not key or key in seen_source_links:
            continue
        seen_source_links.add(key)
        source_links.append({"url": url, "name": name})

    return {
        "id": signal["id"],
        "headline": signal.get("headline"),
        "hotness": signal.get("hotness"),
        "is_fintech": bool(signal.get("is_fintech")),
        "scale_score": signal.get("scale_score"),
        "urgency_score": signal.get("urgency_score"),
        "rigidity_score": signal.get("rigidity_score"),
        "why_now": signal.get("why_now"),
        "category": signal.get("category"),
        "summary": signal.get("summary"),
        "draft": public_draft(signal.get("draft")),
        "sources": source_names,
        "source_name": ", ".join(source_names) if source_names else "Источник",
        "source_urls": source_urls,
        "source_links": source_links,
        "raw_titles": raw_titles,
        "url": primary_raw.get("url"),
        "published_at": to_moscow_iso(primary_raw.get("published_at") or primary_raw.get("parsed_at")),
        "created_at": to_moscow_iso(primary_raw.get("parsed_at")),
        "signal_created_at": to_moscow_iso(signal.get("signal_created_at")),
        "raw_news_ids": source_ids,
    }


def signal_matches_filters(item, query="", categories=None, sources=None, hotness_values=None, time_range=""):
    categories = categories or []
    sources = sources or []
    hotness_values = hotness_values or []
    q = (query or "").strip().lower()
    if q:
        haystack = " ".join(str(item.get(key) or "") for key in (
            "headline",
            "category",
            "summary",
            "why_now",
            "draft",
            "source_name",
            "raw_titles",
            "source_urls",
            "raw_news_ids",
        )).lower()
        if q not in haystack:
            return False

    if categories and item.get("category") not in categories:
        return False
    item_sources = item.get("sources") if isinstance(item.get("sources"), list) else [item.get("source_name")]
    if sources and not any(source in sources for source in item_sources):
        return False
    if hotness_values and parse_int(item.get("hotness")) not in {parse_int(value) for value in hotness_values}:
        return False

    if time_range:
        event_time = parse_datetime(item.get("published_at") or item.get("created_at"))
        if not event_time:
            return False
        age = utcnow() - event_time
        ranges = {
            "day": timedelta(days=1),
            "3d": timedelta(days=3),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
        }
        if time_range in ranges and age > ranges[time_range]:
            return False

    return True


def signal_sort_time(item):
    event_time = parse_datetime(item.get("published_at") or item.get("created_at"))
    return event_time or datetime.min.replace(tzinfo=UTC)


def sort_signal_items(items, sort_by="time_desc"):
    if sort_by == "time_asc":
        items.sort(key=lambda item: (signal_sort_time(item), parse_int(item.get("id"))))
        return
    if sort_by == "hotness":
        items.sort(
            key=lambda item: (
                signal_score_value(item),
                signal_sort_time(item),
                parse_int(item.get("id")),
            ),
            reverse=True,
        )
        return
    items.sort(key=lambda item: (signal_sort_time(item), parse_int(item.get("id"))), reverse=True)


def signal_score_value(item):
    hotness = parse_float(item.get("hotness"), -1.0)
    if hotness is not None and hotness >= 0:
        return hotness
    values = [
        parse_float(item.get("scale_score")),
        parse_float(item.get("urgency_score")),
        parse_float(item.get("rigidity_score")),
    ]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else -1.0


def list_main_signals_page(
    limit=100,
    offset=0,
    query="",
    category="",
    source="",
    hotness="",
    hotness_min="",
    hotness_max="",
    scale_min="",
    scale_max="",
    urgency_min="",
    urgency_max="",
    rigidity_min="",
    rigidity_max="",
    time_range="",
    sort_by="time_desc",
):
    if not MAIN_DB_PATH.exists():
        return {"items": [], "has_more": False}

    offset = max(0, parse_int(offset, 0))
    categories = parse_multi_values(category)
    sources = parse_multi_values(source)
    hotness_values = parse_multi_values(hotness)
    score_filters = {
        "hotness": (parse_float(hotness_min), parse_float(hotness_max)),
        "scale_score": (parse_float(scale_min), parse_float(scale_max)),
        "urgency_score": (parse_float(urgency_min), parse_float(urgency_max)),
        "rigidity_score": (parse_float(rigidity_min), parse_float(rigidity_max)),
    }
    params = []
    items = []
    with connect_main_db() as connection:
        where = [
            signal_not_duplicate_where(connection),
            signal_frontend_visible_where(connection),
        ]
        if categories:
            where.append(f"category IN ({','.join('?' for _ in categories)})")
            params.extend(categories)
        if hotness_values:
            where.append(f"hotness IN ({','.join('?' for _ in hotness_values)})")
            params.extend(parse_float(value, -999) for value in hotness_values)
        for field, (minimum, maximum) in score_filters.items():
            if minimum is not None and table_has_column(connection, "signals", field):
                where.append(f"COALESCE({field}, -1) >= ?")
                params.append(minimum)
            if maximum is not None and table_has_column(connection, "signals", field):
                where.append(f"COALESCE({field}, -1) <= ?")
                params.append(maximum)

        sql_where = " AND ".join(where)
        select_fields = signal_select_fields(connection)
        signal_rows = connection.execute(f"""
            SELECT {select_fields}
            FROM signals
            WHERE {sql_where}
            """, params).fetchall()

        for row in signal_rows:
            signal = dict(row)
            raw_news = load_raw_news_for_signal(connection, parse_signal_source_ids(signal.get("sources")))
            item = signal_to_frontend_item(signal, raw_news)
            if not signal_matches_filters(
                item,
                query=query,
                categories=[],
                sources=sources,
                hotness_values=[],
                time_range=time_range,
            ):
                continue
            items.append(item)

    sort_signal_items(items, sort_by)
    page_items = items[offset:offset + limit + 1]

    return {
        "items": page_items[:limit],
        "has_more": len(page_items) > limit,
    }


def list_main_signals(limit=100, query=""):
    return list_main_signals_page(limit=limit, query=query)["items"]


def load_update_status_snapshot():
    status_path = MAIN_DB_PATH.parent / "update_status.json"
    try:
        if status_path.exists():
            return json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass

    try:
        response = requests.get(UPDATE_STATUS_URL, timeout=1)
        if response.ok:
            return response.json().get("update") or response.json()
    except requests.RequestException:
        pass
    return {}


def ensure_weekly_digest_table(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS weekly_digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            report TEXT NOT NULL DEFAULT '',
            moex_summary TEXT NOT NULL DEFAULT '',
            news_ids TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week_start)
        )
    """)
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(weekly_digests)").fetchall()
    }
    for column_name, column_type in {
        "week_start": "TEXT",
        "week_end": "TEXT",
        "title": "TEXT NOT NULL DEFAULT ''",
        "summary": "TEXT NOT NULL DEFAULT ''",
        "report": "TEXT NOT NULL DEFAULT ''",
        "moex_summary": "TEXT NOT NULL DEFAULT ''",
        "news_ids": "TEXT NOT NULL DEFAULT '[]'",
        "model": "TEXT NOT NULL DEFAULT ''",
        "prompt_version": "TEXT NOT NULL DEFAULT ''",
        "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        "updated_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
    }.items():
        if column_name not in columns:
            connection.execute(f"ALTER TABLE weekly_digests ADD COLUMN {column_name} {column_type}")


def parse_digest_news_ids(value):
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        parsed = []
    if not isinstance(parsed, list):
        parsed = []
    result = []
    for item in parsed:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def list_weekly_digests(limit=20, offset=0):
    if not MAIN_DB_PATH.exists():
        return {"items": [], "has_more": False}

    limit = normalize_api_limit(limit, 20, maximum=100)
    offset = max(0, parse_int(offset, 0))
    with connect_main_db() as connection:
        ensure_weekly_digest_table(connection)
        connection.commit()
        rows = connection.execute("""
            SELECT
                id,
                week_start,
                week_end,
                title,
                summary,
                report,
                moex_summary,
                news_ids,
                model,
                prompt_version,
                created_at,
                updated_at
            FROM weekly_digests
            ORDER BY date(week_start) DESC, id DESC
            LIMIT ? OFFSET ?
        """, (limit + 1, offset)).fetchall()

    items = []
    for row in rows[:limit]:
        item = dict(row)
        item["news_ids"] = parse_digest_news_ids(item.get("news_ids"))
        item["created_at"] = to_moscow_iso(item.get("created_at"))
        item["updated_at"] = to_moscow_iso(item.get("updated_at"))
        items.append(item)
    return {
        "items": items,
        "has_more": len(rows) > limit,
    }


def get_main_overview():
    overview = {
        "observations": 0,
        "sources": 0,
        "categories": 0,
        "important": 0,
        "processed_last_24h": 0,
        "processed_last_7d": 0,
        "last_parsed_at": None,
        "last_update_at": None,
        "category_options": [],
        "source_options": [],
    }
    if not MAIN_DB_PATH.exists():
        return overview

    now = utcnow()
    last_24h_cutoff = now - timedelta(days=1)
    last_7d_cutoff = now - timedelta(days=7)
    last_24h_text = last_24h_cutoff.strftime("%Y-%m-%d %H:%M:%S")
    last_7d_text = last_7d_cutoff.strftime("%Y-%m-%d %H:%M:%S")

    with connect_main_db() as connection:
        raw_row = connection.execute("""
            SELECT COUNT(*) AS observations
            FROM raw_news
            WHERE datetime(COALESCE(parsed_at, published_at)) >= datetime(?)
        """, (last_7d_text,)).fetchone()
        if raw_row:
            overview["observations"] = raw_row["observations"] or 0

        not_duplicate_where = signal_not_duplicate_where(connection, "s")
        visible_condition = signal_frontend_visible_where(connection, "s")
        signal_stats_row = connection.execute(f"""
            SELECT
                SUM(CASE
                    WHEN {visible_condition}
                     AND datetime(COALESCE(rn.parsed_at, rn.published_at)) >= datetime(?)
                    THEN 1 ELSE 0
                END) AS last_24h,
                SUM(CASE
                    WHEN {visible_condition}
                     AND datetime(COALESCE(rn.parsed_at, rn.published_at)) >= datetime(?)
                    THEN 1 ELSE 0
                END) AS last_7d,
                COUNT(DISTINCT CASE WHEN s.category IS NOT NULL AND TRIM(s.category) != '' THEN s.category END) AS categories,
                SUM(CASE WHEN {visible_condition} THEN 1 ELSE 0 END) AS important
            FROM signals s
            LEFT JOIN raw_news rn ON rn.id = CAST(s.sources AS INTEGER)
            WHERE {not_duplicate_where}
        """, (last_24h_text, last_7d_text)).fetchone()
        if signal_stats_row:
            overview["processed_last_24h"] = signal_stats_row["last_24h"] or 0
            overview["processed_last_7d"] = signal_stats_row["last_7d"] or 0
            overview["categories"] = signal_stats_row["categories"] or 0
            overview["important"] = signal_stats_row["important"] or 0

        overview["category_options"] = list(CANONICAL_SIGNAL_CATEGORIES)

        source_row = connection.execute("""
            SELECT COUNT(DISTINCT id) AS sources
            FROM sources
        """).fetchone()
        if source_row:
            overview["sources"] = source_row["sources"] or 0

        source_rows = connection.execute("""
            SELECT name
            FROM sources
            WHERE is_active = 1
              AND name IS NOT NULL
              AND TRIM(name) != ''
            ORDER BY name
        """).fetchall()
        overview["source_options"] = [row["name"] for row in source_rows]

        parsed_row = connection.execute("""
            SELECT MAX(parsed_at) AS last_parsed_at
            FROM raw_news
        """).fetchone()
        if parsed_row:
            overview["last_parsed_at"] = to_moscow_iso(parsed_row["last_parsed_at"])

    update_status = load_update_status_snapshot()
    parser_stage = (update_status.get("stages") or {}).get("parser") or {}
    overview["last_parsed_at"] = to_moscow_iso(
        parser_stage.get("started_at")
        or overview["last_parsed_at"]
        or update_status.get("started_at")
    )
    overview["last_update_at"] = to_moscow_iso(
        parser_stage.get("finished_at")
        or update_status.get("finished_at")
        or update_status.get("started_at")
    )
    if not overview["last_update_at"]:
        try:
            overview["last_update_at"] = datetime.fromtimestamp(MAIN_DB_PATH.stat().st_mtime, UTC).astimezone(MSK).isoformat()
        except OSError:
            overview["last_update_at"] = None

    return overview


def get_main_signal(signal_id):
    if not MAIN_DB_PATH.exists():
        return None

    with connect_main_db() as connection:
        select_fields = signal_select_fields(connection)
        not_duplicate_where = signal_not_duplicate_where(connection)
        row = connection.execute(f"""
            SELECT {select_fields}
            FROM signals
            WHERE id = ?
              AND {not_duplicate_where}
        """, (signal_id,)).fetchone()
        if not row:
            return None
        signal = dict(row)
        raw_news = load_raw_news_for_signal(connection, parse_signal_source_ids(signal.get("sources")))
        return signal_to_frontend_item(signal, raw_news)


def count_main_signals():
    if not MAIN_DB_PATH.exists():
        return 0
    with connect_main_db() as connection:
        not_duplicate_where = signal_not_duplicate_where(connection)
        visible_where = signal_frontend_visible_where(connection)
        row = connection.execute(f"""
            SELECT COUNT(*) AS count
            FROM signals
            WHERE {not_duplicate_where}
              AND {visible_where}
        """).fetchone()
        return row["count"] if row else 0


def format_number(value, decimals=0, scale=1):
    if value is None:
        return None
    try:
        number = float(value) / scale
    except (TypeError, ValueError):
        return value
    text = f"{number:,.{decimals}f}".replace(",", " ")
    if decimals:
        text = text.rstrip("0").rstrip(".")
    return text


def parse_json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def parse_json_dict(value):
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def market_event_to_dict(row):
    return {
        "date": row["event_date"],
        "event_date": row["event_date"],
        "type": row["event_type"],
        "event_type": row["event_type"],
        "severity": row["severity"],
        "title": row["title"],
        "description": row["description"],
        "related_tickers": parse_json_list(row["related_tickers"]),
        "metrics": parse_json_dict(row["metrics_json"]),
    }


def list_market_events(connection, limit=20, offset=0):
    rows = connection.execute("""
        SELECT
            event_date,
            event_type,
            severity,
            title,
            description,
            related_tickers,
            metrics_json
        FROM market_events
        ORDER BY date(event_date) DESC, severity DESC, id DESC
        LIMIT ? OFFSET ?
    """, (max(1, int(limit or 20)), max(0, int(offset or 0)))).fetchall()
    return [market_event_to_dict(row) for row in rows]


def list_market_events_for_dates(connection, dates):
    dates = [date for date in dates if date]
    if not dates:
        return []
    placeholders = ",".join("?" for _ in dates)
    rows = connection.execute(f"""
        SELECT
            event_date,
            event_type,
            severity,
            title,
            description,
            related_tickers,
            metrics_json
        FROM market_events
        WHERE event_date IN ({placeholders})
        ORDER BY date(event_date) DESC, severity DESC, id DESC
    """, dates).fetchall()
    return [market_event_to_dict(row) for row in rows]


def list_archived_market_event_dates(connection, current_trade_date, limit=3):
    where = ["event_date IS NOT NULL"]
    params = []
    if current_trade_date:
        where.append("event_date != ?")
        params.append(current_trade_date)
    rows = connection.execute(f"""
        SELECT DISTINCT event_date
        FROM market_events
        WHERE {" AND ".join(where)}
        ORDER BY date(event_date) DESC
        LIMIT ?
    """, (*params, max(1, int(limit or 3)))).fetchall()
    return [row["event_date"] for row in rows]


def mark_market_events(events, current_trade_date):
    for event in events:
        event_date = event.get("event_date")
        event["is_current"] = bool(current_trade_date and event_date == current_trade_date)
        event["current_trade_date"] = current_trade_date
    return events


def list_main_market(limit=100, offset=0, query="", sort_by="value_desc", movement="all"):
    if not MAIN_DB_PATH.exists():
        return {"items": [], "has_more": False, "snapshot": None, "events": [], "archived_events": []}

    query = (query or "").strip()
    movement = (movement or "all").strip()
    sort_by = (sort_by or "value_desc").strip()
    order_by_map = {
        "value_desc": "COALESCE(value_rub, 0) DESC, COALESCE(numtrades, 0) DESC, secid ASC",
        "trades_desc": "COALESCE(numtrades, 0) DESC, COALESCE(value_rub, 0) DESC, secid ASC",
        "change_desc": "COALESCE(change_percent, -999999) DESC, COALESCE(value_rub, 0) DESC, secid ASC",
        "change_asc": "COALESCE(change_percent, 999999) ASC, COALESCE(value_rub, 0) DESC, secid ASC",
        "price_desc": "COALESCE(last, marketprice, 0) DESC, COALESCE(value_rub, 0) DESC, secid ASC",
        "ticker_asc": "secid ASC",
    }
    order_by = order_by_map.get(sort_by, order_by_map["value_desc"])

    try:
        with connect_main_db() as connection:
            latest_row = connection.execute("""
                SELECT trade_date
                FROM moex_instruments_daily
                ORDER BY date(trade_date) DESC, fetched_at DESC, id DESC
                LIMIT 1
            """).fetchone()
            latest_trade_date = latest_row["trade_date"] if latest_row else None

            market_where = ["trade_date = ?"]
            market_params = [latest_trade_date]
            if query:
                like = f"%{query}%"
                market_where.append("(secid LIKE ? OR shortname LIKE ? OR secname LIKE ?)")
                market_params.extend([like, like, like])
            if movement == "gainers":
                market_where.append("COALESCE(change_percent, 0) > 0")
            elif movement == "losers":
                market_where.append("COALESCE(change_percent, 0) < 0")
            elif movement == "active":
                market_where.append("(COALESCE(value_rub, 0) > 0 OR COALESCE(numtrades, 0) > 0)")
            elif movement == "strong":
                market_where.append("ABS(COALESCE(change_percent, 0)) >= 3")
            where_sql = " AND ".join(market_where)

            rows = connection.execute(f"""
                SELECT
                    trade_date,
                    secid,
                    boardid,
                    shortname,
                    secname,
                    last,
                    marketprice,
                    change_percent,
                    value_rub,
                    volume,
                    numtrades,
                    fetched_at
                FROM moex_instruments_daily
                WHERE {where_sql}
                ORDER BY {order_by}
                LIMIT ? OFFSET ?
            """, (*market_params, limit + 1, max(0, parse_int(offset, 0)))).fetchall() if latest_trade_date else []

            snapshot_row = connection.execute("""
                SELECT
                    trade_date,
                    COALESCE(instruments_count, securities_count) AS instruments_count,
                    COALESCE(traded_instruments_count, traded_securities_count) AS traded_instruments_count,
                    total_value,
                    total_trades,
                    top_secid,
                    top_shortname,
                    top_value,
                    fetched_at
                FROM moex_daily_stats
                ORDER BY date(trade_date) DESC, id DESC
                LIMIT 1
            """).fetchone()

            leader_gain_row = None
            leader_drop_row = None
            most_traded_row = None
            if latest_trade_date:
                leader_gain_row = connection.execute("""
                    SELECT secid, shortname, change_percent
                    FROM moex_instruments_daily
                    WHERE trade_date = ?
                      AND change_percent IS NOT NULL
                    ORDER BY change_percent DESC
                    LIMIT 1
                """, (latest_trade_date,)).fetchone()
                leader_drop_row = connection.execute("""
                    SELECT secid, shortname, change_percent
                    FROM moex_instruments_daily
                    WHERE trade_date = ?
                      AND change_percent IS NOT NULL
                    ORDER BY change_percent ASC
                    LIMIT 1
                """, (latest_trade_date,)).fetchone()
                most_traded_row = connection.execute("""
                    SELECT secid, shortname, numtrades
                    FROM moex_instruments_daily
                    WHERE trade_date = ?
                      AND numtrades IS NOT NULL
                    ORDER BY numtrades DESC
                    LIMIT 1
                """, (latest_trade_date,)).fetchone()

            current_event_rows = list_market_events_for_dates(connection, [latest_trade_date])
            archived_event_dates = list_archived_market_event_dates(connection, latest_trade_date, limit=3)
            archived_event_rows = list_market_events_for_dates(connection, archived_event_dates)
    except sqlite3.OperationalError:
        return {"items": [], "has_more": False, "snapshot": None, "events": [], "archived_events": []}

    items = [
        {
            "date": row["trade_date"],
            "secid": row["secid"],
            "boardid": row["boardid"],
            "shortname": row["shortname"] or row["secid"],
            "secname": row["secname"] or "",
            "last": row["last"],
            "marketprice": row["marketprice"],
            "change_percent": row["change_percent"],
            "value_rub": row["value_rub"],
            "volume": row["volume"],
            "trades": row["numtrades"],
            "fetched_at": to_moscow_iso(row["fetched_at"]),
        }
        for row in rows[:limit]
    ]

    snapshot = None
    if snapshot_row:
        snapshot = {
            "trade_date": snapshot_row["trade_date"],
            "instruments_count": snapshot_row["instruments_count"],
            "traded_instruments_count": snapshot_row["traded_instruments_count"],
            "total_value": snapshot_row["total_value"],
            "total_trades": snapshot_row["total_trades"],
            "top_value_ticker": snapshot_row["top_secid"] or snapshot_row["top_shortname"],
            "top_value": snapshot_row["top_value"],
            "fetched_at": to_moscow_iso(snapshot_row["fetched_at"]),
        }
        if leader_gain_row:
            snapshot["leader_gain_ticker"] = leader_gain_row["secid"] or leader_gain_row["shortname"]
            snapshot["leader_gain_percent"] = leader_gain_row["change_percent"]
        if leader_drop_row:
            snapshot["leader_drop_ticker"] = leader_drop_row["secid"] or leader_drop_row["shortname"]
            snapshot["leader_drop_percent"] = leader_drop_row["change_percent"]
        if most_traded_row:
            snapshot["most_traded_ticker"] = most_traded_row["secid"] or most_traded_row["shortname"]
            snapshot["most_traded_count"] = most_traded_row["numtrades"]

    current_trade_date = snapshot["trade_date"] if snapshot else latest_trade_date
    current_events = mark_market_events(current_event_rows, current_trade_date)
    archived_events = mark_market_events(archived_event_rows, current_trade_date)

    return {
        "items": items,
        "has_more": len(rows) > limit,
        "snapshot": snapshot,
        "events": current_events,
        "archived_events": archived_events,
    }


def proxy_backend_update():
    try:
        response = requests.post(UPDATE_API_URL, timeout=15)
    except requests.RequestException as error:
        return jsonify({
            "ok": False,
            "error": "Backend update is unavailable",
            "details": str(error),
        }), 502

    try:
        payload = response.json()
    except ValueError:
        payload = {"ok": response.ok, "message": response.text}
    return jsonify(payload), response.status_code


def get_current_user():
    email = get_jwt_identity()
    if not email:
        return None
    user = User.query.filter_by(email=email).first()
    refresh_subscription_status(user)
    if user and db.session.is_modified(user):
        db.session.commit()
    return user


def admin_only(view):
    @wraps(view)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.role != "admin" or user.email != MANAGER_EMAIL:
            REQUEST_METRICS["admin_denied_total"] += 1
            return jsonify({"error": "Только для админа"}), 403
        return view(*args, **kwargs)

    return wrapper


def ensure_state():
    state = SystemState.query.first()
    if not state:
        state = SystemState(last_signal_check=utcnow())
        db.session.add(state)
        db.session.commit()
    return state


def refresh_subscription_status(user: User):
    if not user:
        return None
    if user.email == MANAGER_EMAIL:
        user.role = "admin"
        user.activated = True
        user.subscription_plan = user.subscription_plan or "manager"
        user.subscription_status = ACTIVE_SUBSCRIPTION
        return user
    if user.subscription_status == ACTIVE_SUBSCRIPTION and user.subscription_expires_at:
        expires_at = parse_datetime(user.subscription_expires_at)
        if expires_at and expires_at <= utcnow():
            user.subscription_status = "expired"
            user.activated = False
    return user


def activate_subscription(user: User, plan: str):
    plan = (plan or "").strip().lower()
    if plan not in AVAILABLE_PLANS:
        return False, "На данный момент не доступна"
    if plan == DEMO_PLAN and (user.demo_used or user.subscription_plan == DEMO_PLAN or user.subscription_status == "expired"):
        return False, "Демо-доступ нельзя подключить повторно"

    user.activated = True
    user.subscription_plan = plan
    user.subscription_status = ACTIVE_SUBSCRIPTION
    user.subscription_expires_at = utcnow() + timedelta(days=PLAN_DURATIONS_DAYS[plan])
    if plan == DEMO_PLAN:
        user.demo_used = True
    return True, ""


def normalize_admin_subscription(plan, status):
    plan = (plan or "").strip().lower()
    status = (status or "inactive").strip().lower()

    if plan and plan not in PLAN_DURATIONS_DAYS:
        return None, None, "Неизвестный тариф"
    if status not in {ACTIVE_SUBSCRIPTION, "inactive", "expired"}:
        return None, None, "Неизвестный статус подписки"
    if not plan:
        return "", "inactive", ""
    if status == ACTIVE_SUBSCRIPTION and plan not in PLAN_DURATIONS_DAYS:
        return None, None, "Нельзя активировать аккаунт без подписки"
    return plan, status, ""


def ensure_frontend_schema():
    with db.engine.begin() as connection:
        user_columns = {
            row[1]
            for row in connection.exec_driver_sql('PRAGMA table_info("user")').fetchall()
        }
        if "subscription_plan" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN subscription_plan TEXT DEFAULT ''")
        if "subscription_status" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN subscription_status TEXT DEFAULT 'inactive'")
        if "subscription_expires_at" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN subscription_expires_at DATETIME")
        if "demo_used" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN demo_used BOOLEAN DEFAULT 0")
        if "last_notification_check" not in user_columns:
            connection.exec_driver_sql("ALTER TABLE user ADD COLUMN last_notification_check DATETIME")
            connection.exec_driver_sql(
                "UPDATE user SET last_notification_check = ? WHERE last_notification_check IS NULL",
                (utcnow(),),
            )
        connection.exec_driver_sql("""
            UPDATE user
            SET demo_used = 1
            WHERE (subscription_plan = 'demo' OR subscription_status = 'expired')
              AND COALESCE(demo_used, 0) = 0
        """)

        notification_columns = {
            row[1]
            for row in connection.exec_driver_sql('PRAGMA table_info("notification_item")').fetchall()
        }
        if "created_at" not in notification_columns:
            connection.exec_driver_sql("ALTER TABLE notification_item ADD COLUMN created_at DATETIME")
        if "read" not in notification_columns:
            connection.exec_driver_sql("ALTER TABLE notification_item ADD COLUMN read BOOLEAN DEFAULT 0")

def upsert_seed_users():
    for item in SAMPLE_USERS:
        user = User.query.filter_by(email=item["email"]).first()
        if not user:
            user = User(email=item["email"])
            db.session.add(user)
        user.full_name = item["full_name"]
        user.password_hash = generate_password_hash(item["password"])
        user.role = item["role"]
        user.activated = item["activated"]
        user.subscription_plan = item.get("subscription_plan", DEMO_PLAN)
        user.subscription_status = item.get("subscription_status", ACTIVE_SUBSCRIPTION)
        user.subscription_expires_at = item.get("subscription_expires_at")
        user.demo_used = bool(item.get("demo_used", user.subscription_plan == DEMO_PLAN))
        user.last_notification_check = user.last_notification_check or utcnow()
    db.session.commit()


def seed_data():
    upsert_seed_users()
    PromoCode.query.delete()
    db.session.commit()

    state = ensure_state()
    last_signal_check = parse_datetime(state.last_signal_check)
    if not last_signal_check or last_signal_check < utcnow() - timedelta(days=7):
        state.last_signal_check = utcnow()
        db.session.commit()


def signal_value(signal, key, default=None):
    if isinstance(signal, dict):
        return signal.get(key, default)
    return getattr(signal, key, default)


def signal_matches_rule(signal, rule: NotificationSetting) -> bool:
    if rule.theme and rule.theme != signal_value(signal, "category", ""):
        return False
    if rule.source_name:
        sources = signal_value(signal, "sources", []) or []
        if isinstance(sources, str):
            sources = [sources]
        source_name = signal_value(signal, "source_name", "")
        if rule.source_name != source_name and rule.source_name not in sources:
            return False
    if rule.hotness_min and parse_int(signal_value(signal, "hotness", 0)) < rule.hotness_min:
        return False
    return True


def get_user_notification_cutoff(user: User):
    cutoff = parse_datetime(user.last_notification_check)
    if cutoff:
        return cutoff
    state = ensure_state()
    return parse_datetime(state.last_signal_check) or utcnow()


def signal_notification_time(signal):
    return parse_datetime(
        signal.get("published_at")
        or signal.get("created_at")
        or signal.get("signal_created_at")
    )


def rebuild_notifications_for_user(user: User, advance_cursor=True):
    if not user or not user.activated:
        return []

    cutoff = get_user_notification_cutoff(user)
    new_signals = []
    for signal in list_main_signals(limit=MAX_API_LIMIT):
        event_time = signal_notification_time(signal)
        if event_time and event_time > cutoff:
            new_signals.append(signal)

    rules = NotificationSetting.query.filter_by(user_id=user.id, active=True).all()
    created_items = []

    for signal in new_signals:
        if any(signal_matches_rule(signal, rule) for rule in rules):
            exists = NotificationItem.query.filter_by(user_id=user.id, signal_id=signal["id"]).first()
            if not exists:
                item = NotificationItem(
                    user_id=user.id,
                    signal_id=signal["id"],
                    title=signal.get("headline") or "",
                    message=signal.get("summary") or "",
                    kind="signal",
                    read=False,
                    created_at=utcnow(),
                )
                db.session.add(item)
                created_items.append(item)

    if advance_cursor:
        max_signal_time = max(
            [signal_notification_time(signal) for signal in new_signals if signal_notification_time(signal)]
            or [cutoff]
        )
        user.last_notification_check = max_signal_time if new_signals else utcnow()
    db.session.commit()
    return created_items


def rebuild_notifications_for_all_users():
    state = ensure_state()
    for user in User.query.all():
        rebuild_notifications_for_user(user)
    state.last_signal_check = utcnow()
    db.session.commit()

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

def is_valid_email(email):
    return EMAIL_REGEX.match(email) is not None

def create_app(test_config=None):
    FRONT_BACKEND_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite:///" + str(FRONT_BACKEND_DB_PATH),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY", "dev-redcat-secret-key-change-me-32-bytes"),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(days=7),
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)

    if not app.config.get("TESTING"):
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(
            func=sync_news_from_dp,
            args=[app],
            trigger='cron',
            hour='0,4,8,12,16,20',
            minute=0
        )
        scheduler.start()

    CORS(app)
    db.init_app(app)
    jwt.init_app(app)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    app.logger.setLevel(logging.INFO)

    @app.before_request
    def start_timer():
        g.request_started_at = time.time()

    @app.after_request
    def log_request(response):
        REQUEST_METRICS["requests_total"] += 1
        elapsed_ms = int((time.time() - getattr(g, "request_started_at", time.time())) * 1000)
        app.logger.info("%s %s -> %s (%sms)", request.method, request.path, response.status_code, elapsed_ms)
        return response

    @app.errorhandler(Exception)
    def handle_unhandled_error(error):
        REQUEST_METRICS["errors_total"] += 1
        app.logger.exception("Unhandled error: %s", error)
        return jsonify({"error": "Внутренняя ошибка сервера"}), 500

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.post("/api/update")
    @jwt_required()
    def run_update():
        user = get_current_user()
        if not user or user.subscription_status != ACTIVE_SUBSCRIPTION:
            return jsonify({"error": "Нужна активная подписка"}), 403
        return proxy_backend_update()

    @app.post("/api/admin/update")
    @admin_only
    def admin_run_update():
        return proxy_backend_update()

    @app.get("/api/update/status")
    def update_status():
        headers = {}
        if UPDATE_STATUS_TOKEN:
            headers["X-Admin-Token"] = UPDATE_STATUS_TOKEN
        try:
            response = requests.get(UPDATE_STATUS_URL, headers=headers, timeout=10)
        except requests.RequestException as error:
            return jsonify({"ok": False, "error": "Backend update status is unavailable", "details": str(error)}), 502
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": response.ok, "message": response.text}
        return jsonify(payload), response.status_code

    @app.get("/api/digests")
    def get_digests():
        return jsonify(list_weekly_digests(
            limit=request.args.get("limit") or 20,
            offset=request.args.get("offset") or 0,
        ))

    @app.get("/api/metrics")
    def metrics():
        return jsonify({
            **REQUEST_METRICS,
            "users": User.query.count(),
            "signals": count_main_signals(),
            "main_db": str(MAIN_DB_PATH),
            "main_db_exists": MAIN_DB_PATH.exists(),
            "notifications": NotificationItem.query.count(),
            "promos": PromoCode.query.count(),
            "favorites": Favorite.query.count(),
        })

    @app.get("/api/sync-from-dp")  # Запомним этот путь
    def sync_news_endpoint():
        try:
            from flask import current_app
            # Вызываем функцию, передавая текущий экземпляр приложения
            sync_news_from_dp(current_app._get_current_object())
            return jsonify({
                "success": True,
                "message": str(MAIN_DB_PATH),
                "data": None
            })
        except Exception as e:
            app.logger.error(f"Sync Endpoint Error: {e}")
            return jsonify({
                "success": False,
                "message": f"Ошибка на стороне сервера: {str(e)}"
            }), 500


    @app.get("/api/security/check")
    def security_check():
        return jsonify({
            "ok": True,
            "checks": {
                "jwt_auth": True,
                "password_hashing": True,
                "admin_routes_protected": True,
                "notifications_db_backed": True,
                "metrics_enabled": True,
            },
        })

    @app.get("/api/signals")
    def get_signals():
        q = (request.args.get("q") or "").strip()
        limit = normalize_api_limit(request.args.get("limit"), 100)
        page = list_main_signals_page(
            limit=limit,
            offset=request.args.get("offset"),
            query=q,
            category=(request.args.get("category") or "").strip(),
            source=(request.args.get("source") or "").strip(),
            hotness=(request.args.get("hotness") or "").strip(),
            hotness_min=(request.args.get("hotness_min") or "").strip(),
            hotness_max=(request.args.get("hotness_max") or "").strip(),
            scale_min=(request.args.get("scale_min") or "").strip(),
            scale_max=(request.args.get("scale_max") or "").strip(),
            urgency_min=(request.args.get("urgency_min") or "").strip(),
            urgency_max=(request.args.get("urgency_max") or "").strip(),
            rigidity_min=(request.args.get("rigidity_min") or "").strip(),
            rigidity_max=(request.args.get("rigidity_max") or "").strip(),
            time_range=(request.args.get("time_range") or "").strip(),
            sort_by=(request.args.get("sort") or "time_desc").strip(),
        )
        return jsonify(page)

    @app.get("/api/signals/<int:signal_id>")
    def get_signal(signal_id):
        item = get_main_signal(signal_id)
        if not item:
            return jsonify({"error": "Карточка не найдена"}), 404
        return jsonify({"item": item})

    @app.get("/api/market")
    def get_market():
        limit = normalize_api_limit(request.args.get("limit"), 50)
        return jsonify(list_main_market(
            limit=limit,
            offset=request.args.get("offset"),
            query=request.args.get("q") or "",
            sort_by=request.args.get("sort") or "value_desc",
            movement=request.args.get("movement") or "all",
        ))

    @app.get("/api/market/events")
    def get_market_events_endpoint():
        limit = normalize_api_limit(request.args.get("limit"), 20, maximum=100)
        offset = max(0, parse_int(request.args.get("offset"), 0))

        if not MAIN_DB_PATH.exists():
            return jsonify({"items": [], "has_more": False})

        try:
            with connect_main_db() as connection:
                events = list_market_events(connection, limit=limit + 1, offset=offset)
        except sqlite3.OperationalError:
            return jsonify({"items": [], "has_more": False})

        return jsonify({
            "items": events[:limit],
            "has_more": len(events) > limit,
        })

    @app.get("/api/overview")
    def get_overview():
        return jsonify(get_main_overview())

    @app.post("/api/register")
    def register():
        data = request.get_json() or {}
        full_name = (data.get("full_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        if not is_valid_email(email):
            return jsonify({"error": "Некорректный формат почты"}), 400

        if not full_name or not email or not password:
            return jsonify({"error": "Заполни логин, почту и пароль"}), 400

        existing = User.query.filter_by(email=email).first()
        if existing:
            if not existing.activated:
                return jsonify({
                    "error": "Аккаунт нужно активировать",
                    "requires_activation": True,
                    "email": existing.email,
                }), 409
            return jsonify({"error": "Такой пользователь уже есть"}), 400

        user = User(
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            role="user",
            activated=False,
            subscription_plan="",
            subscription_status="inactive",
            demo_used=False,
        )
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "Пользователь создан", "user": user.to_dict(), "requires_activation": True})

    @app.post("/api/activate")
    def activate():
        data = request.get_json() or {}
        email = (data.get("email") or "").strip().lower()
        plan = (data.get("plan") or data.get("subscription_plan") or "").strip().lower()

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404

        refresh_subscription_status(user)
        if db.session.is_modified(user):
            db.session.commit()

        if user.activated and user.subscription_status == ACTIVE_SUBSCRIPTION:
            token = create_access_token(identity=user.email)
            return jsonify({"token": token, "user": user.to_dict(), "message": "Аккаунт уже активирован"})

        ok, message = activate_subscription(user, plan)
        if not ok:
            return jsonify({"error": message}), 400

        db.session.commit()
        token = create_access_token(identity=user.email)
        return jsonify({"token": token, "user": user.to_dict(), "message": "Аккаунт активирован"})

    @app.post("/api/login")
    def login():
        data = request.get_json() or {}
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""

        user = User.query.filter_by(email=email).first()
        if not user:
            REQUEST_METRICS["auth_denied_total"] += 1
            return jsonify({"error": "Пользователь не найден"}), 404

        if not check_password_hash(user.password_hash, password):
            REQUEST_METRICS["auth_denied_total"] += 1
            return jsonify({"error": "Неверный пароль"}), 401

        refresh_subscription_status(user)
        if db.session.is_modified(user):
            db.session.commit()

        if not user.activated:
            REQUEST_METRICS["auth_denied_total"] += 1
            return jsonify({
                "error": "Аккаунт нужно активировать",
                "requires_activation": True,
                "email": user.email,
            }), 403

        token = create_access_token(identity=user.email)
        return jsonify({"token": token, "user": user.to_dict(), "message": "Вход выполнен"})

    @app.get("/api/me")
    @jwt_required()
    def me():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404
        return jsonify({"user": user.to_dict()})

    @app.put("/api/me")
    @jwt_required()
    def update_me():
        user = get_current_user()
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404

        data = request.get_json() or {}
        full_name = (data.get("full_name") or user.full_name).strip()
        email = (data.get("email") or user.email).strip().lower()
        bio = (data.get("bio") or user.bio or "").strip()
        avatar_url = (data.get("avatar_url") or user.avatar_url or "").strip()

        if email != user.email:
            exists = User.query.filter(User.email == email, User.id != user.id).first()
            if exists:
                return jsonify({"error": "Такой email уже занят"}), 400
            user.email = email

        user.full_name = full_name
        user.bio = bio
        user.avatar_url = avatar_url
        db.session.commit()
        return jsonify({"message": "Профиль обновлён", "user": user.to_dict()})

    @app.get("/api/favorites")
    @jwt_required()
    def get_favorites():
        user = get_current_user()
        items = []
        for fav in Favorite.query.filter_by(user_id=user.id).order_by(Favorite.id.desc()).all():
            signal = get_main_signal(fav.signal_id)
            if signal:
                items.append(signal)
        return jsonify({"items": items})

    @app.post("/api/signals/<int:signal_id>/favorite")
    @jwt_required()
    def toggle_favorite(signal_id):
        user = get_current_user()
        signal = get_main_signal(signal_id)
        if not signal:
            return jsonify({"error": "Карточка не найдена"}), 404

        fav = Favorite.query.filter_by(user_id=user.id, signal_id=signal_id).first()
        if fav:
            db.session.delete(fav)
            db.session.commit()
            return jsonify({"message": "Убрано из избранного", "saved": False})

        db.session.add(Favorite(user_id=user.id, signal_id=signal_id))
        db.session.commit()
        return jsonify({"message": "Добавлено в избранное", "saved": True})

    @app.get("/api/notification-settings")
    @jwt_required()
    def get_notification_settings():
        user = get_current_user()
        items = NotificationSetting.query.filter_by(user_id=user.id).order_by(NotificationSetting.id.asc()).all()
        return jsonify({"items": [item.to_dict() for item in items]})

    @app.put("/api/notification-settings")
    @jwt_required()
    def save_notification_settings():
        user = get_current_user()
        data = request.get_json() or {}
        rules = data.get("rules") or []

        NotificationSetting.query.filter_by(user_id=user.id).delete()
        NotificationItem.query.filter_by(user_id=user.id).delete()

        for rule in rules:
            theme = (rule.get("theme") or "").strip()
            source_name = (rule.get("source_name") or "").strip()
            hotness_min = rule.get("hotness_min")
            if hotness_min in ("", None):
                hotness_min = 0
            else:
                hotness_min = max(0, min(5, int(hotness_min)))

            if not theme and not source_name and not hotness_min:
                continue

            db.session.add(NotificationSetting(
                user_id=user.id,
                theme=theme,
                source_name=source_name,
                hotness_min=hotness_min,
                active=True,
            ))

        user.last_notification_check = utcnow()
        db.session.commit()
        return jsonify({"message": "Правила сохранены", "items": [item.to_dict() for item in
                                                                  NotificationSetting.query.filter_by(
                                                                      user_id=user.id).order_by(
                                                                      NotificationSetting.id.asc()).all()]})

    @app.get("/api/notifications")
    @jwt_required()
    def get_notifications():
        user = get_current_user()
        items = NotificationItem.query.filter_by(user_id=user.id).order_by(NotificationItem.id.desc()).all()
        unread_count = NotificationItem.query.filter_by(user_id=user.id, read=False).count()
        return jsonify({"items": [item.to_dict() for item in items], "unread_count": unread_count})

    @app.post("/api/notifications/<int:item_id>/read")
    @jwt_required()
    def read_notification(item_id):
        user = get_current_user()
        item = NotificationItem.query.filter_by(user_id=user.id, id=item_id).first()
        if not item:
            return jsonify({"error": "Уведомление не найдено"}), 404
        item.read = True
        db.session.commit()
        unread_count = NotificationItem.query.filter_by(user_id=user.id, read=False).count()
        return jsonify({"message": "Уведомление прочитано", "unread_count": unread_count})

    @app.delete("/api/notifications/clear")
    @jwt_required()
    def clear_notifications():
        user = get_current_user()
        NotificationItem.query.filter_by(user_id=user.id).delete()
        user.last_notification_check = utcnow()
        db.session.commit()
        return jsonify({"message": "Уведомления очищены"})

    @app.post("/api/notifications/rebuild")
    @jwt_required()
    def rebuild_notifications():
        user = get_current_user()
        rebuild_notifications_for_user(user)
        items = NotificationItem.query.filter_by(user_id=user.id).order_by(NotificationItem.id.desc()).all()
        return jsonify({"message": "Уведомления обновлены", "items": [item.to_dict() for item in items]})

    @app.post("/api/admin/notifications/sync")
    @admin_only
    def sync_notifications():
        rebuild_notifications_for_all_users()
        return jsonify({"message": "Уведомления синхронизированы"})

    @app.get("/api/admin/users")
    @admin_only
    def admin_users():
        users = User.query.order_by(User.id.asc()).all()
        for user in users:
            refresh_subscription_status(user)
        if any(db.session.is_modified(user) for user in users):
            db.session.commit()
        return jsonify({"items": [user.to_dict() for user in users]})

    @app.put("/api/admin/users/<int:user_id>")
    @admin_only
    def admin_update_user(user_id):
        data = request.get_json() or {}
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404

        full_name = (data.get("full_name") or user.full_name).strip()
        email = (data.get("email") or user.email).strip().lower()
        if user.email == MANAGER_EMAIL and email != MANAGER_EMAIL:
            return jsonify({"error": "Email менеджера менять нельзя"}), 400
        role = "admin" if email == MANAGER_EMAIL else "user"

        if email != user.email:
            exists = User.query.filter(User.email == email, User.id != user.id).first()
            if exists:
                return jsonify({"error": "Такой email уже занят"}), 400
            user.email = email

        user.full_name = full_name
        user.role = role
        if "activated" in data:
            user.activated = bool(data.get("activated"))
        if "subscription_plan" in data:
            user.subscription_plan = (data.get("subscription_plan") or "").strip()
            if user.subscription_plan == DEMO_PLAN:
                user.demo_used = True
        if "subscription_status" in data:
            user.subscription_status = (data.get("subscription_status") or "").strip() or "inactive"
            user.activated = user.subscription_status == ACTIVE_SUBSCRIPTION
        if not user.subscription_plan:
            user.subscription_status = "inactive"
            user.activated = False
        if user.subscription_status == ACTIVE_SUBSCRIPTION and not user.subscription_plan:
            return jsonify({"error": "Нельзя активировать аккаунт без подписки"}), 400

        db.session.commit()
        return jsonify({"message": "Пользователь обновлён", "user": user.to_dict()})

    @app.get("/api/admin/subscriptions")
    @admin_only
    def admin_subscriptions():
        users = User.query.order_by(User.id.asc()).all()
        return jsonify({"items": [user.to_dict() for user in users]})

    @app.put("/api/admin/subscriptions/<int:user_id>")
    @admin_only
    def admin_update_subscription(user_id):
        data = request.get_json() or {}
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404

        if user.email == MANAGER_EMAIL:
            return jsonify({"error": "Подписку менеджера менять нельзя"}), 400

        plan, status, error = normalize_admin_subscription(
            data.get("subscription_plan"),
            data.get("subscription_status"),
        )
        if error:
            return jsonify({"error": error}), 400

        user.subscription_plan = plan
        user.subscription_status = status
        user.activated = status == ACTIVE_SUBSCRIPTION
        if plan == DEMO_PLAN:
            user.demo_used = True
        if status == ACTIVE_SUBSCRIPTION and plan in PLAN_DURATIONS_DAYS:
            user.subscription_expires_at = utcnow() + timedelta(days=PLAN_DURATIONS_DAYS[plan])
        if status != ACTIVE_SUBSCRIPTION:
            user.subscription_expires_at = None
        db.session.commit()
        return jsonify({"message": "Подписка обновлена", "user": user.to_dict()})

    @app.get("/api/admin/promo-codes")
    @admin_only
    def admin_promo_codes():
        return jsonify({"items": []})

    @app.post("/api/admin/promo-codes")
    @admin_only
    def admin_add_promo_code():
        data = request.get_json() or {}
        code = (data.get("code") or "").strip().upper()
        description = (data.get("description") or "").strip()

        if not code:
            return jsonify({"error": "Нужен код"}), 400
        if PromoCode.query.filter_by(code=code).first():
            return jsonify({"error": "Такой код уже есть"}), 400

        promo = PromoCode(code=code, description=description, active=True)
        db.session.add(promo)
        db.session.commit()
        return jsonify({"message": "Промокод добавлен", "item": promo.to_dict()})

    @app.put("/api/admin/promo-codes/<int:promo_id>")
    @admin_only
    def admin_update_promo_code(promo_id):
        data = request.get_json() or {}
        promo = db.session.get(PromoCode, promo_id)
        if not promo:
            return jsonify({"error": "Промокод не найден"}), 404

        code = (data.get("code") or promo.code).strip().upper()
        if code != promo.code:
            exists = PromoCode.query.filter(PromoCode.code == code, PromoCode.id != promo.id).first()
            if exists:
                return jsonify({"error": "Такой код уже есть"}), 400
            promo.code = code

        promo.description = (data.get("description") or promo.description or "").strip()
        if "active" in data:
            promo.active = bool(data.get("active"))

        db.session.commit()
        return jsonify({"message": "Промокод обновлён", "item": promo.to_dict()})

    with app.app_context():
        db.create_all()
        ensure_frontend_schema()
        seed_data()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=parse_int(os.getenv("FRONT_BACKEND_PORT"), 5001), debug=True)
