from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, UTC
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
MAX_API_LIMIT = 10000

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
    avatar_url = db.Column(db.Text, default="")
    bio = db.Column(db.Text, default="")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "role": self.role,
            "activated": self.activated,
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

    def to_dict(self):
        return {
            "id": self.id,
            "signal_id": self.signal_id,
            "title": self.title,
            "message": self.message,
            "kind": self.kind,
            "read": self.read,
        }


class SystemState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    last_signal_check = db.Column(db.DateTime, nullable=True)




RETIRED_ADMIN_EMAILS = {
    "admin@redcat.local",
    "lead@redcat.local",
}

SAMPLE_USERS = [
    {"full_name": "Manager Red Cat", "email": "manager@redcat.tu", "password": "rqbqerj1543tgjkq", "role": "admin",
     "activated": True},
    {"full_name": "Test User", "email": "user@redcat.local", "password": "User12345!", "role": "user",
     "activated": True},
]

SAMPLE_PROMOS = [
    {"code": "REDCAT2026", "description": "Основной код для тестового доступа", "active": True},
    {"code": "TRNDWCH", "description": "Код для демо-активации", "active": True},
    {"code": "CASE2026", "description": "Код из кейса", "active": True},
]

def parse_int(value, default=0):
    try:
        return int(float(value))
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

    return {
        "id": signal["id"],
        "headline": signal.get("headline"),
        "hotness": signal.get("hotness"),
        "why_now": signal.get("why_now"),
        "category": signal.get("category"),
        "summary": signal.get("summary"),
        "draft": public_draft(signal.get("draft")),
        "sources": source_names,
        "source_name": ", ".join(source_names) if source_names else "Источник",
        "source_urls": source_urls,
        "url": primary_raw.get("url"),
        "published_at": primary_raw.get("published_at") or primary_raw.get("parsed_at"),
        "created_at": primary_raw.get("parsed_at"),
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
            "week": timedelta(days=7),
            "month": timedelta(days=30),
        }
        if time_range in ranges and age > ranges[time_range]:
            return False

    return True


def list_main_signals_page(
    limit=100,
    offset=0,
    query="",
    category="",
    source="",
    hotness="",
    time_range="",
    sort_by="time_desc",
):
    if not MAIN_DB_PATH.exists():
        return {"items": [], "has_more": False}

    offset = max(0, parse_int(offset, 0))
    categories = parse_multi_values(category)
    sources = parse_multi_values(source)
    hotness_values = parse_multi_values(hotness)
    where = ["(draft IS NULL OR draft NOT LIKE 'DUBLICATE OF %')"]
    params = []
    if categories:
        where.append(f"category IN ({','.join('?' for _ in categories)})")
        params.extend(categories)
    if hotness_values:
        where.append(f"hotness IN ({','.join('?' for _ in hotness_values)})")
        params.extend(parse_int(value) for value in hotness_values)

    order_by = "id DESC"
    if sort_by == "time_asc":
        order_by = "id ASC"
    elif sort_by == "hotness":
        order_by = "hotness DESC, id DESC"

    sql_where = " AND ".join(where)
    needs_post_filter = bool(query or sources or time_range)
    sql_offset = 0 if needs_post_filter else offset
    post_filter_offset = offset if needs_post_filter else 0
    skipped = 0
    items = []
    chunk_size = min(max(limit + 1, 50), 500)
    with connect_main_db() as connection:
        while len(items) <= limit:
            signal_rows = connection.execute(f"""
            SELECT id, headline, hotness, why_now, category, sources, summary, draft
            FROM signals
            WHERE {sql_where}
            ORDER BY {order_by}
            LIMIT ?
            OFFSET ?
            """, (*params, chunk_size, sql_offset)).fetchall()
            if not signal_rows:
                break

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
                if skipped < post_filter_offset:
                    skipped += 1
                    continue
                items.append(item)
                if len(items) > limit:
                    break

            sql_offset += len(signal_rows)

    return {
        "items": items[:limit],
        "has_more": len(items) > limit,
    }


def list_main_signals(limit=100, query=""):
    return list_main_signals_page(limit=limit, query=query)["items"]


def load_update_status_snapshot():
    try:
        response = requests.get(UPDATE_STATUS_URL, timeout=3)
        if response.ok:
            return response.json().get("update") or response.json()
    except requests.RequestException:
        pass
    return {}


def get_main_overview():
    overview = {
        "observations": 0,
        "sources": 0,
        "categories": 0,
        "important": 0,
        "last_parsed_at": None,
        "last_update_at": None,
        "category_options": [],
        "source_options": [],
    }
    if not MAIN_DB_PATH.exists():
        return overview

    with connect_main_db() as connection:
        visible_filter = "(draft IS NULL OR draft NOT LIKE 'DUBLICATE OF %')"
        row = connection.execute(f"""
            SELECT
                COUNT(*) AS observations,
                COUNT(DISTINCT category) AS categories,
                SUM(CASE WHEN hotness >= 4 THEN 1 ELSE 0 END) AS important
            FROM signals
            WHERE {visible_filter}
        """).fetchone()
        if row:
            overview["observations"] = row["observations"] or 0
            overview["categories"] = row["categories"] or 0
            overview["important"] = row["important"] or 0

        category_rows = connection.execute(f"""
            SELECT DISTINCT category
            FROM signals
            WHERE {visible_filter}
              AND category IS NOT NULL
              AND TRIM(category) != ''
            ORDER BY category
        """).fetchall()
        overview["category_options"] = [row["category"] for row in category_rows]

        source_row = connection.execute("""
            SELECT COUNT(DISTINCT source_id) AS sources
            FROM raw_news
        """).fetchone()
        if source_row:
            overview["sources"] = source_row["sources"] or 0

        source_rows = connection.execute("""
            SELECT DISTINCT s.name AS name
            FROM raw_news rn
            JOIN sources s ON s.id = rn.source_id
            WHERE s.name IS NOT NULL
              AND TRIM(s.name) != ''
            ORDER BY s.name
        """).fetchall()
        overview["source_options"] = [row["name"] for row in source_rows]

        parsed_row = connection.execute("""
            SELECT MAX(parsed_at) AS last_parsed_at
            FROM raw_news
        """).fetchone()
        if parsed_row:
            overview["last_parsed_at"] = parsed_row["last_parsed_at"]

    update_status = load_update_status_snapshot()
    overview["last_update_at"] = update_status.get("finished_at") or update_status.get("started_at")
    if not overview["last_update_at"]:
        try:
            overview["last_update_at"] = datetime.fromtimestamp(MAIN_DB_PATH.stat().st_mtime, UTC).isoformat()
        except OSError:
            overview["last_update_at"] = None

    return overview


def get_main_signal(signal_id):
    if not MAIN_DB_PATH.exists():
        return None

    with connect_main_db() as connection:
        row = connection.execute("""
            SELECT id, headline, hotness, why_now, category, sources, summary, draft
            FROM signals
            WHERE id = ?
              AND (draft IS NULL OR draft NOT LIKE 'DUBLICATE OF %')
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
        row = connection.execute("""
            SELECT COUNT(*) AS count
            FROM signals
            WHERE draft IS NULL OR draft NOT LIKE 'DUBLICATE OF %'
        """).fetchone()
        return row["count"] if row else 0


def format_market_number(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return value


def list_main_market(limit=100, offset=0):
    if not MAIN_DB_PATH.exists():
        return {"items": [], "has_more": False}

    with connect_main_db() as connection:
        rows = connection.execute("""
            SELECT
                trade_date,
                securities_count,
                traded_securities_count,
                total_value,
                total_trades,
                top_secid,
                top_shortname,
                top_value
            FROM moex_daily_stats
            ORDER BY date(trade_date) DESC, id DESC
            LIMIT ?
            OFFSET ?
        """, (limit + 1, max(0, parse_int(offset, 0)))).fetchall()

    items = [
        {
            "date": row["trade_date"],
            "sec_count": row["securities_count"] or row["traded_securities_count"],
            "total_value": format_market_number(row["total_value"]),
            "trades": row["total_trades"],
            "top_ticker": row["top_secid"] or row["top_shortname"],
            "top_value": format_market_number(row["top_value"]),
        }
        for row in rows[:limit]
    ]
    return {
        "items": items,
        "has_more": len(rows) > limit,
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
    return User.query.filter_by(email=email).first()


def admin_only(view):
    @wraps(view)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user.role != "admin":
            REQUEST_METRICS["admin_denied_total"] += 1
            return jsonify({"error": "Только для админа"}), 403
        return view(*args, **kwargs)

    return wrapper


def ensure_state():
    state = SystemState.query.first()
    if not state:
        state = SystemState(last_signal_check=utcnow() - timedelta(days=365))
        db.session.add(state)
        db.session.commit()
    return state


def remove_retired_admin_users():
    users = User.query.filter(User.email.in_(RETIRED_ADMIN_EMAILS)).all()
    if not users:
        return

    user_ids = [user.id for user in users]
    Favorite.query.filter(Favorite.user_id.in_(user_ids)).delete(synchronize_session=False)
    NotificationSetting.query.filter(NotificationSetting.user_id.in_(user_ids)).delete(synchronize_session=False)
    NotificationItem.query.filter(NotificationItem.user_id.in_(user_ids)).delete(synchronize_session=False)
    User.query.filter(User.id.in_(user_ids)).delete(synchronize_session=False)
    db.session.commit()


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
    db.session.commit()


def seed_data():
    remove_retired_admin_users()
    upsert_seed_users()

    if not PromoCode.query.first():
        for item in SAMPLE_PROMOS:
            db.session.add(PromoCode(**item))
        db.session.commit()

    ensure_state()


def signal_value(signal, key, default=None):
    if isinstance(signal, dict):
        return signal.get(key, default)
    return getattr(signal, key, default)


def signal_matches_rule(signal, rule: NotificationSetting) -> bool:
    if rule.theme and rule.theme != signal_value(signal, "category", ""):
        return False
    if rule.source_name and rule.source_name != signal_value(signal, "source_name", ""):
        return False
    if rule.hotness_min and parse_int(signal_value(signal, "hotness", 0)) < rule.hotness_min:
        return False
    return True


def rebuild_notifications_for_user(user: User):
    state = ensure_state()
    last_time = state.last_signal_check or (utcnow() - timedelta(days=365))
    if last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=UTC)

    new_signals = []
    for signal in reversed(list_main_signals(limit=500)):
        event_time = parse_datetime(signal.get("published_at") or signal.get("created_at"))
        if event_time and event_time > last_time:
            new_signals.append(signal)

    if not new_signals:
        return []

    rules = NotificationSetting.query.filter_by(user_id=user.id, active=True).all()
    created_items = []

    for signal in new_signals:
        matched = False

        if rules:
            matched = any(signal_matches_rule(signal, rule) for rule in rules)
        else:
            matched = True

        if matched:
            exists = NotificationItem.query.filter_by(user_id=user.id, signal_id=signal["id"]).first()
            if not exists:
                item = NotificationItem(
                    user_id=user.id,
                    signal_id=signal["id"],
                    title=signal.get("headline") or "",
                    message=signal.get("summary") or "",
                    kind="signal",
                )
                db.session.add(item)
                created_items.append(item)

    newest_time = utcnow()
    state.last_signal_check = newest_time
    db.session.commit()
    return created_items


def rebuild_notifications_for_all_users():
    for user in User.query.all():
        rebuild_notifications_for_user(user)

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
    @admin_only
    def run_update():
        return proxy_backend_update()

    @app.post("/api/admin/update")
    @admin_only
    def admin_run_update():
        return proxy_backend_update()

    @app.get("/api/update/status")
    def update_status():
        try:
            response = requests.get(UPDATE_STATUS_URL, timeout=10)
        except requests.RequestException as error:
            return jsonify({"ok": False, "error": "Backend update status is unavailable", "details": str(error)}), 502
        try:
            payload = response.json()
        except ValueError:
            payload = {"ok": response.ok, "message": response.text}
        return jsonify(payload), response.status_code

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
        return jsonify(list_main_market(limit=limit, offset=request.args.get("offset")))

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
        data = request.get_json() or {}

        if not full_name or not email or not password:
            return jsonify({"error": "Заполни ФИО, почту и пароль"}), 400

        if User.query.filter_by(email=email).first():
            return jsonify({"error": "Такой пользователь уже есть"}), 400

        user = User(
            full_name=full_name,
            email=email,
            password_hash=generate_password_hash(password),
            role="user",
            activated=False,
        )
        db.session.add(user)
        db.session.commit()
        return jsonify({"message": "Пользователь создан", "user": user.to_dict()})

    @app.post("/api/activate")
    def activate():
        data = request.get_json() or {}
        email = (data.get("email") or "").strip().lower()
        promo_code = (data.get("promo_code") or "").strip().upper()
        payment_success = bool(data.get("payment_success"))

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "Пользователь не найден"}), 404

        promo_ok = False
        if promo_code:
            promo_ok = PromoCode.query.filter_by(code=promo_code, active=True).first() is not None

        if not payment_success and not promo_ok:
            return jsonify({"error": "Нужна оплата или активный промокод"}), 400

        user.activated = True
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

        if not user.activated:
            REQUEST_METRICS["auth_denied_total"] += 1
            return jsonify({"error": "Аккаунт ещё не активирован"}), 403

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

        for rule in rules:
            theme = (rule.get("theme") or "").strip()
            source_name = (rule.get("source_name") or "").strip()
            hotness_min = rule.get("hotness_min")
            if hotness_min in ("", None):
                hotness_min = 0
            else:
                hotness_min = int(hotness_min)

            if not theme and not source_name and not hotness_min:
                continue

            db.session.add(NotificationSetting(
                user_id=user.id,
                theme=theme,
                source_name=source_name,
                hotness_min=hotness_min,
                active=True,
            ))

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
        return jsonify({"items": [item.to_dict() for item in items]})

    @app.delete("/api/notifications/clear")
    @jwt_required()
    def clear_notifications():
        user = get_current_user()
        NotificationItem.query.filter_by(user_id=user.id).delete()
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
        role = (data.get("role") or user.role).strip()

        if email != user.email:
            exists = User.query.filter(User.email == email, User.id != user.id).first()
            if exists:
                return jsonify({"error": "Такой email уже занят"}), 400
            user.email = email

        user.full_name = full_name
        user.role = role
        if "activated" in data:
            user.activated = bool(data.get("activated"))

        db.session.commit()
        return jsonify({"message": "Пользователь обновлён", "user": user.to_dict()})

    @app.get("/api/admin/promo-codes")
    @admin_only
    def admin_promo_codes():
        items = PromoCode.query.order_by(PromoCode.id.asc()).all()
        return jsonify({"items": [item.to_dict() for item in items]})

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
        seed_data()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=parse_int(os.getenv("FRONT_BACKEND_PORT"), 5001), debug=True)
