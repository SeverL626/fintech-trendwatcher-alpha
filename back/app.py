import json
import hmac
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

try:
    from back.init_db import DB_PATH, connect_db
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db


MSK_TZ = ZoneInfo("Europe/Moscow")
PARSER_SCHEDULE_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
PARSER_PERIOD_HOURS = 3
PARSER_LOCK_PATH = Path(DB_PATH).parent / "parser.lock"
UPDATE_MANUAL_COOLDOWN_SECONDS = 60 * 60
UPDATE_LAST_START_PATH = Path(DB_PATH).parent / "update_last_start.json"
LEGACY_PARSER_MANUAL_THROTTLE_PATH = Path(DB_PATH).parent / "parser_manual_throttle.json"
PARSER_TIMEOUT_SECONDS = 60 * 60
PARSER_STATUS_PATH = Path(DB_PATH).parent / "parser_status.json"
MODEL_TIMEOUT_SECONDS = 60 * 60
MODEL_STATUS_PATH = Path(DB_PATH).parent / "model_status.json"
MODEL_OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it")
OPENROUTER_EMBEDDING_MODEL = "openai/text-embedding-3-large"
MODEL_MAX_REQUESTS_PER_RUN = None
UPDATE_PARSER_ONLY = os.getenv("UPDATE_PARSER_ONLY", "0") == "1"
UPDATE_TIMEOUT_SECONDS = 60 * 60
UPDATE_STATUS_PATH = Path(DB_PATH).parent / "update_status.json"
UPDATE_STATUS_TOKEN = os.getenv("UPDATE_STATUS_TOKEN", "")
BOOT_ID = f"{os.getpid()}-{uuid.uuid4().hex}"
BOOT_STARTED_AT = datetime.now(MSK_TZ)

app = Flask(__name__)
app.config["DB_PATH"] = DB_PATH
app.json.ensure_ascii = False
app.json.compact = False

_scheduler_started = False
_scheduler_start_lock = threading.Lock()


@app.after_request
def add_cors_headers(response):
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Admin-Token")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
    return response


@app.route("/api/<path:_path>", methods=["OPTIONS"])
@app.route("/update", methods=["OPTIONS"])
@app.route("/update/status", methods=["OPTIONS"])
@app.route("/signals", methods=["OPTIONS"])
def options_response(_path=None):
    return ("", 204)


@app.route("/")
def hello():
    return jsonify({
        "ok": True,
        "service": "Fintech Trendwatcher",
        "current_time": {
            "timezone": "Europe/Moscow",
            "iso": now_msk().isoformat(timespec="seconds"),
        },
        "update": get_update_overview(),
        "routes": [
            "/update",
            "/update/status",
            "/signals",
        ],
    })


@app.route("/update")
def run_update():
    update_result, status_code = start_update_job_background("manual")
    return jsonify({
        "ok": status_code == 202,
        "update": update_result,
    }), status_code


@app.route("/update/status")
def update_status():
    token_error = require_update_status_token()
    if token_error:
        return token_error
    status = get_update_status()
    return jsonify({
        "ok": status.get("state") != "failed",
        "update": status,
    })


@app.route("/signals")
def signals():
    limit = request.args.get("limit", 20)
    try:
        from model.signal_processor import list_signals
    except ModuleNotFoundError:
        from signal_processor import list_signals

    return jsonify({
        "ok": True,
        "signals": list_signals(app.config["DB_PATH"], limit),
    })


@app.route("/api/signals")
def api_signals():
    limit = normalize_api_limit(request.args.get("limit"), default=100, maximum=10000)
    return jsonify({
        "ok": True,
        "items": list_frontend_signals(app.config["DB_PATH"], limit),
    })


@app.route("/api/market")
def api_market():
    limit = normalize_api_limit(request.args.get("limit"), default=50, maximum=10000)
    return jsonify({
        "ok": True,
        "items": list_frontend_market(app.config["DB_PATH"], limit),
    })


@app.route("/api/admin/update", methods=["POST"])
@app.route("/api/update", methods=["POST"])
@app.route("/update", methods=["POST"])
def api_run_update():
    update_result, status_code = start_update_job_background("manual")
    return jsonify({
        "ok": status_code == 202,
        "update": update_result,
    }), status_code


@app.route("/api/update/status")
def api_update_status():
    token_error = require_update_status_token()
    if token_error:
        return token_error
    status = get_update_status()
    return jsonify({
        "ok": status.get("state") != "failed",
        "update": status,
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    payload = request.get_json(silent=True) or {}
    return jsonify(make_auth_payload(payload))


@app.route("/api/register", methods=["POST"])
def api_register():
    payload = request.get_json(silent=True) or {}
    return jsonify(make_auth_payload(payload))


@app.route("/api/activate", methods=["POST"])
def api_activate():
    payload = request.get_json(silent=True) or {}
    return jsonify(make_auth_payload(payload))


@app.route("/api/me", methods=["GET", "PUT"])
def api_me():
    payload = request.get_json(silent=True) or {}
    return jsonify({
        "ok": True,
        "user": make_frontend_user(payload),
    })


@app.route("/api/favorites")
def api_favorites():
    return jsonify({"ok": True, "items": []})


@app.route("/api/signals/<int:signal_id>/favorite", methods=["POST"])
def api_toggle_favorite(signal_id):
    return jsonify({"ok": True, "signal_id": signal_id})


@app.route("/api/notifications")
def api_notifications():
    return jsonify({"ok": True, "items": []})


@app.route("/api/notifications/clear", methods=["DELETE"])
def api_notifications_clear():
    return jsonify({"ok": True, "items": []})


@app.route("/api/notifications/rebuild", methods=["POST"])
def api_notifications_rebuild():
    return jsonify({"ok": True, "items": []})


@app.route("/api/notification-settings", methods=["GET", "PUT"])
def api_notification_settings():
    payload = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "items": payload.get("rules") or []})


@app.route("/api/admin/users")
def api_admin_users():
    return jsonify({"ok": True, "items": [make_frontend_user({})]})


@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
def api_admin_user_update(user_id):
    payload = request.get_json(silent=True) or {}
    user = make_frontend_user(payload)
    user["id"] = user_id
    return jsonify({"ok": True, "user": user})


@app.route("/api/admin/promo-codes", methods=["GET", "POST"])
def api_admin_promo_codes():
    return jsonify({"ok": True, "items": []})


@app.route("/api/admin/promo-codes/<int:promo_id>", methods=["PUT"])
def api_admin_promo_code_update(promo_id):
    return jsonify({"ok": True, "id": promo_id})


def list_frontend_signals(db_path, limit):
    with connect_db(db_path) as db:
        signal_rows = db.execute("""
            SELECT id, headline, hotness, why_now, category, sources, summary, draft
            FROM signals
            WHERE draft IS NULL OR draft NOT LIKE 'DUBLICATE OF %'
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()

        items = []
        for row in signal_rows:
            signal = dict(row)
            raw_news = load_raw_news_for_signal(db, parse_signal_source_ids(signal.get("sources")))
            primary_raw = raw_news[0] if raw_news else {}
            source_names = unique_values(raw_row.get("source_name") for raw_row in raw_news)
            source_urls = unique_values(raw_row.get("url") for raw_row in raw_news)

            items.append({
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
                "raw_news_ids": parse_signal_source_ids(signal.get("sources")),
            })
        return items


def make_auth_payload(payload):
    return {
        "ok": True,
        "token": "local-admin",
        "user": make_frontend_user(payload),
    }


def make_frontend_user(payload):
    full_name = str(payload.get("full_name") or "Admin").strip() or "Admin"
    email = str(payload.get("email") or "admin@example.local").strip() or "admin@example.local"
    return {
        "id": 1,
        "full_name": full_name,
        "email": email,
        "role": payload.get("role") or "admin",
        "activated": bool(payload.get("activated", True)),
        "bio": payload.get("bio") or "",
        "avatar_url": payload.get("avatar_url") or "",
    }


def load_raw_news_for_signal(db, raw_news_ids):
    if not raw_news_ids:
        return []

    placeholders = ",".join("?" for _ in raw_news_ids)
    rows = db.execute(f"""
        SELECT
            rn.id,
            rn.url,
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


def list_frontend_market(db_path, limit):
    with connect_db(db_path) as db:
        rows = db.execute("""
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
        """, (limit,)).fetchall()

        return [
            {
                "date": row["trade_date"],
                "sec_count": row["securities_count"] or row["traded_securities_count"],
                "total_value": format_market_number(row["total_value"]),
                "trades": row["total_trades"],
                "top_ticker": row["top_secid"] or row["top_shortname"],
                "top_value": format_market_number(row["top_value"]),
            }
            for row in rows
        ]


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


def format_market_number(value):
    if value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return value


def normalize_api_limit(value, default=100, maximum=10000):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(maximum, limit))


def require_update_status_token():
    if not UPDATE_STATUS_TOKEN:
        return None
    if is_valid_update_status_token():
        return None
    return jsonify({
        "ok": False,
        "error": "Unauthorized",
    }), 401


def is_valid_update_status_token():
    token = (
        request.headers.get("X-Admin-Token")
        or request.args.get("token")
        or request.args.get("auth")
        or bearer_token_from_header(request.headers.get("Authorization"))
        or ""
    )
    return hmac.compare_digest(token, UPDATE_STATUS_TOKEN)


def bearer_token_from_header(value):
    value = str(value or "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value[7:].strip()


def run_parser_from_db(db_path, progress_callback=None):
    try:
        from back.parser import run_parser_from_db as parser_runner
    except ModuleNotFoundError:
        from parser import run_parser_from_db as parser_runner

    return parser_runner(db_path, progress_callback=progress_callback)


def run_model_from_db(db_path, limit=None):
    try:
        from model.signal_processor import process_new_raw_news
    except ModuleNotFoundError:
        from signal_processor import process_new_raw_news

    return process_new_raw_news(db_path, limit)


def run_duplicates_from_db(db_path):
    try:
        from model.duplicate_processor import process_signal_duplicates
    except ModuleNotFoundError:
        from duplicate_processor import process_signal_duplicates

    return process_signal_duplicates(db_path)


def ensure_model_configured():
    try:
        from model.signal_processor import ensure_model_configured as check_configured
    except ModuleNotFoundError:
        from signal_processor import ensure_model_configured as check_configured

    return check_configured()


def now_msk():
    return datetime.now(MSK_TZ)


def get_parser_update_settings():
    current_time = now_msk()
    return {
        "enabled": False,
        "message": "Parser runs only as the first stage of /update",
        "timezone": "Europe/Moscow",
        "schedule": [f"{hour:02d}:00" for hour in PARSER_SCHEDULE_HOURS],
        "period_hours": PARSER_PERIOD_HOURS,
        "stale_lock_after_minutes": PARSER_TIMEOUT_SECONDS // 60,
        "next_run_at": get_next_parser_run_at(current_time).isoformat(timespec="seconds"),
    }


def get_model_update_settings():
    return {
        "enabled": False,
        "message": "Model runs only as the second stage of /update",
        "provider": "openrouter",
        "mode": "single_model",
        "model": MODEL_OPENROUTER_MODEL,
        "max_requests_per_run": "all",
        "input_status": "new",
        "writes_to": "signals",
        "updates_raw_news_statuses": ["processing", "processed", "error"],
        "manual_start": None,
        "message": "Model stage runs only as part of /update",
        "status_url": None,
        "signals_url": "/signals",
        "stale_lock_after_minutes": MODEL_TIMEOUT_SECONDS // 60,
        "shared_lock": {
            "path": str(PARSER_LOCK_PATH),
            "message": "Parser and model cannot run at the same time",
        },
    }


def get_update_settings():
    current_time = now_msk()
    return {
        "enabled": True,
        "timezone": "Europe/Moscow",
        "schedule": [f"{hour:02d}:00" for hour in PARSER_SCHEDULE_HOURS],
        "period_hours": PARSER_PERIOD_HOURS,
        "stale_lock_after_minutes": UPDATE_TIMEOUT_SECONDS // 60,
        "stages": ["parser"] if UPDATE_PARSER_ONLY else ["parser", "model", "duplicates"],
        "model_max_requests_per_run": "all",
        "embedding_model": OPENROUTER_EMBEDDING_MODEL,
        "parser_only": UPDATE_PARSER_ONLY,
        "manual_cooldown_minutes": UPDATE_MANUAL_COOLDOWN_SECONDS // 60,
        "manual_cooldown_scope": "previous update start, manual or auto",
        "auto_skips_only_when_running": True,
        "next_run_at": get_next_parser_run_at(current_time).isoformat(timespec="seconds"),
        "manual_start": "/update",
        "status_url": "/update/status",
    }


def get_update_overview():
    stages = [
        {
            "name": "parser",
            "description": "Collects new raw_news from active sources",
        },
    ]
    if not UPDATE_PARSER_ONLY:
        stages.extend([
            {
                "name": "model",
                "description": "Processes new raw_news into signals",
                "provider": "openrouter",
                "model": MODEL_OPENROUTER_MODEL,
                "max_requests_per_run": "all",
            },
            {
                "name": "duplicates",
                "description": "Merges semantic duplicates and marks secondary signals",
                "provider": "openrouter",
                "model": OPENROUTER_EMBEDDING_MODEL,
            },
        ])

    return {
        "enabled": True,
        "timezone": "Europe/Moscow",
        "schedule": [f"{hour:02d}:00" for hour in PARSER_SCHEDULE_HOURS],
        "period_hours": PARSER_PERIOD_HOURS,
        "next_run_at": get_next_parser_run_at().isoformat(timespec="seconds"),
        "stale_lock_after_minutes": UPDATE_TIMEOUT_SECONDS // 60,
        "manual_cooldown_minutes": UPDATE_MANUAL_COOLDOWN_SECONDS // 60,
        "manual_cooldown_scope": "previous update start, manual or auto",
        "auto_skips_only_when_running": True,
        "parser_only": UPDATE_PARSER_ONLY,
        "stages": stages,
        "manual_start": "/update",
        "status_url": "/update/status",
    }


def start_update_job_background(trigger):
    lock_fd = acquire_parser_lock("update")
    if lock_fd is None:
        return {
            "status": "busy",
            "message": "Update is already running",
            "trigger": trigger,
            "status_url": "/update/status",
        }, 409

    if trigger == "manual":
        cooldown_response = get_manual_update_cooldown_response()
        if cooldown_response:
            cooldown_response["status_url"] = "/update/status"
            release_parser_lock(lock_fd)
            return cooldown_response, 429

    if not UPDATE_PARSER_ONLY:
        try:
            ensure_model_configured()
        except Exception as error:
            release_parser_lock(lock_fd)
            return {
                "status": "error",
                "message": str(error),
                "trigger": trigger,
                "status_url": "/update/status",
            }, 500

    started_at = now_msk()
    try:
        save_update_started_at(started_at, trigger)
        save_update_running_status(trigger, started_at)
    except OSError as error:
        release_parser_lock(lock_fd)
        return {
            "status": "error",
            "message": f"Failed to save update state: {error}",
            "trigger": trigger,
            "status_url": "/update/status",
        }, 500

    thread = threading.Thread(
        target=run_update_job_background,
        args=(trigger, lock_fd, started_at),
        name=f"update-{trigger}",
        daemon=True,
    )
    thread.start()

    return {
        "status": "Started",
        "message": "Update started in background",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "status_url": "/update/status",
    }, 202


def run_update_job_background(trigger, lock_fd, started_at):
    try:
        result = run_update_job_with_lock(trigger, started_at)
        parser_summary = result.get("summary", {}).get("parser", {})
        model_summary = result.get("summary", {}).get("model", {})
        duplicates_summary = result.get("summary", {}).get("duplicates", {})
        print(
            f"Update {trigger} finished at {result['finished_at']} "
            f"with parser_created={parser_summary.get('created', 0)} "
            f"signals_created={model_summary.get('signals_created', 0)} "
            f"duplicates_marked={duplicates_summary.get('duplicates_marked', 0)}",
            flush=True,
        )
    except Exception as error:
        finished_at = now_msk()
        save_update_failed_status(trigger, started_at, finished_at, error)
        print(
            f"Update {trigger} failed at {finished_at.isoformat(timespec='seconds')}: {error}",
            flush=True,
        )
    finally:
        release_parser_lock(lock_fd)


def run_update_job_with_lock(trigger, started_at):
    save_update_stage_status(trigger, started_at, "parser", "running")
    parser_started_at = now_msk()
    save_parser_running_status(trigger, parser_started_at)
    try:
        parser_result = run_parser_from_db(
            app.config["DB_PATH"],
            progress_callback=lambda event, source, index, total, result=None: save_parser_progress_status(
                trigger,
                started_at,
                parser_started_at,
                event,
                source,
                index,
                total,
                result,
            ),
        )
    except Exception as error:
        save_update_stage_status(
            trigger,
            started_at,
            "parser",
            "failed",
            started_at=parser_started_at,
            finished_at=now_msk(),
            error=error,
        )
        raise

    parser_finished_at = now_msk()
    parser_summary = make_parser_stage_summary(parser_result)
    save_update_stage_status(
        trigger,
        started_at,
        "parser",
        "finished",
        started_at=parser_started_at,
        finished_at=parser_finished_at,
        summary=parser_summary,
        result=parser_result,
    )
    save_parser_finished_status(trigger, parser_started_at, parser_finished_at, parser_result)

    if UPDATE_PARSER_ONLY:
        finished_at = now_msk()
        result = {
            "state": "finished",
            "message": "Update finished in parser-only mode",
            "trigger": trigger,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
            "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
            "parser_only": True,
            "summary": {
                "parser": parser_summary,
            },
            "stages": {
                "parser": {
                    "state": "finished",
                    "summary": parser_summary,
                },
            },
        }
        save_update_status(result)
        return result

    save_update_stage_status(trigger, started_at, "model", "running")
    model_started_at = now_msk()
    save_model_running_status(model_started_at, None)
    try:
        model_result = run_model_from_db(app.config["DB_PATH"], None)
    except Exception as error:
        save_update_stage_status(
            trigger,
            started_at,
            "model",
            "failed",
            started_at=model_started_at,
            finished_at=now_msk(),
            error=error,
        )
        raise

    model_finished_at = now_msk()
    model_summary = make_model_stage_summary(model_result)
    save_update_stage_status(
        trigger,
        started_at,
        "model",
        "finished",
        started_at=model_started_at,
        finished_at=model_finished_at,
        summary=model_summary,
        result=model_result,
    )
    save_model_finished_status(model_started_at, model_finished_at, model_result, None)

    save_update_stage_status(trigger, started_at, "duplicates", "running")
    duplicates_started_at = now_msk()
    try:
        duplicates_result = run_duplicates_from_db(app.config["DB_PATH"])
    except Exception as error:
        save_update_stage_status(
            trigger,
            started_at,
            "duplicates",
            "failed",
            started_at=duplicates_started_at,
            finished_at=now_msk(),
            error=error,
        )
        raise

    duplicates_finished_at = now_msk()
    duplicates_summary = make_duplicates_stage_summary(duplicates_result)
    save_update_stage_status(
        trigger,
        started_at,
        "duplicates",
        "finished",
        started_at=duplicates_started_at,
        finished_at=duplicates_finished_at,
        summary=duplicates_summary,
        result=duplicates_result,
    )

    finished_at = now_msk()
    result = {
        "state": "finished",
        "message": "Update finished",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
        "summary": {
            "parser": parser_summary,
            "model": model_summary,
            "duplicates": duplicates_summary,
        },
        "stages": {
            "parser": {
                "state": "finished",
                "summary": parser_summary,
            },
            "model": {
                "state": "finished",
                "summary": model_summary,
            },
            "duplicates": {
                "state": "finished",
                "summary": duplicates_summary,
            },
        },
    }
    save_update_status(result)
    return result


def get_update_status():
    status = load_update_status()
    if not status:
        return {
            "state": "idle",
            "message": "Update has not been started yet",
            "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
        }

    if is_unfinished_running_status(status):
        if is_runtime_lock_interrupted():
            finished_at = now_msk()
            status.update({
                "state": "failed",
                "message": "Update interrupted because backend process stopped",
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "duration_seconds": get_status_duration_seconds(status, finished_at),
                "error": "Backend process was stopped before update finished; stale runtime lock was detected",
                "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
            })
            mark_running_stages_interrupted(status)
            save_update_status(status)
            remove_stale_parser_lock(force=True)
            return status

        status["state"] = "running"
        started_at = parse_msk_datetime(status.get("started_at"))
        if started_at:
            duration_seconds = max(0, int((now_msk() - started_at).total_seconds()))
            status["duration_seconds"] = duration_seconds
            status["message"] = "Update is running"
            status["stale_lock_after_seconds"] = UPDATE_TIMEOUT_SECONDS
            save_update_status(status)

    return status


def get_status_duration_seconds(status, finished_at):
    started_at = parse_msk_datetime(status.get("started_at"))
    if not started_at:
        return status.get("duration_seconds", 0)
    return max(0, int((finished_at - started_at).total_seconds()))


def mark_running_stages_interrupted(status):
    stages = status.get("stages") or {}
    finished_at = status.get("finished_at")
    for stage_status in stages.values():
        if isinstance(stage_status, dict) and stage_status.get("state") == "running":
            stage_status["state"] = "failed"
            stage_status["message"] = "stage interrupted"
            stage_status["finished_at"] = finished_at
            stage_status["error"] = "Backend process stopped before this stage finished"


def is_unfinished_running_status(status):
    if status.get("state") == "running":
        return True
    if status.get("state") != "timed_out" or status.get("finished_at"):
        return False

    stages = status.get("stages") or {}
    return any(
        isinstance(stage_status, dict) and stage_status.get("state") == "running"
        for stage_status in stages.values()
    )


def load_update_status():
    try:
        return json.loads(UPDATE_STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_update_running_status(trigger, started_at):
    stages = {
        "parser": {"state": "pending", "message": "Parser has not started yet"},
    }
    if not UPDATE_PARSER_ONLY:
        stages.update({
            "model": {"state": "pending", "message": "Model has not started yet"},
            "duplicates": {"state": "pending", "message": "Duplicates has not started yet"},
        })

    save_update_status({
        "state": "running",
        "message": "Update is running",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": 0,
        "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
        "parser_only": UPDATE_PARSER_ONLY,
        "summary": {},
        "stages": stages,
    })


def save_update_stage_status(
    trigger,
    update_started_at,
    stage,
    state,
    started_at=None,
    finished_at=None,
    summary=None,
    result=None,
    error=None,
):
    status = load_update_status() or {}
    stages = status.get("stages") or {}
    stage_status = {
        "state": state,
        "message": f"{stage} {state}",
    }
    if started_at:
        stage_status["started_at"] = started_at.isoformat(timespec="seconds")
    if finished_at:
        stage_status["finished_at"] = finished_at.isoformat(timespec="seconds")
        if started_at:
            stage_status["duration_seconds"] = max(0, int((finished_at - started_at).total_seconds()))
    if summary is not None:
        stage_status["summary"] = summary
    if result is not None:
        stage_status["result"] = compact_stage_result(stage, result)
    if error is not None:
        stage_status["error"] = str(error)

    stages[stage] = stage_status
    status.update({
        "state": "running",
        "message": f"Update is running: {stage} {state}",
        "trigger": trigger,
        "started_at": update_started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": max(0, int((now_msk() - update_started_at).total_seconds())),
        "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
        "stages": stages,
    })
    save_update_status(status)


def save_update_failed_status(trigger, started_at, finished_at, error):
    status = load_update_status() or {}
    status.update({
        "state": "failed",
        "message": "Update failed",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "error": str(error),
        "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
    })
    save_update_status(status)


def save_update_status(status):
    UPDATE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def make_parser_stage_summary(result):
    return {
        "sources": result.get("sources", 0),
        "created": result.get("created", 0),
        "duplicates": result.get("duplicates", 0),
        "skipped": result.get("skipped", 0),
        "errors": result.get("errors", 0),
        "empty_sources": result.get("empty_sources", 0),
    }


def make_model_stage_summary(result):
    openrouter_usage = result.get("openrouter") or {}
    return {
        "processed_items": result.get("processed_items", 0),
        "signals_created": result.get("signals_created", 0),
        "errors": result.get("errors", 0),
        "rate_limited": result.get("rate_limited", False),
        "run_cost": openrouter_usage.get("run_cost"),
        "requests_sent": openrouter_usage.get("requests_sent"),
    }


def make_duplicates_stage_summary(result):
    openrouter_usage = result.get("openrouter") or {}
    return {
        "lookback_signals": result.get("lookback_signals", 0),
        "processed_signals": result.get("processed_signals", 0),
        "compared_signals": result.get("compared_signals", 0),
        "excluded_signals": result.get("excluded_signals", 0),
        "embedded_signals": result.get("embedded_signals", 0),
        "duplicates_marked": result.get("duplicates_marked", 0),
        "merged_sources": result.get("merged_sources", 0),
        "embedding_model": result.get("embedding_model", OPENROUTER_EMBEDDING_MODEL),
        "pca": result.get("pca"),
        "run_cost": openrouter_usage.get("run_cost"),
        "requests_sent": openrouter_usage.get("requests_sent"),
    }


def compact_stage_result(stage, result):
    if stage == "parser":
        return make_parser_stage_summary(result)
    if stage == "model":
        return make_model_stage_summary(result)
    if stage == "duplicates":
        return make_duplicates_stage_summary(result)
    return result


def get_model_status():
    status = load_model_status()
    if not status:
        return {
            "state": "idle",
            "message": "Model processing has not been started yet",
            "stale_lock_after_seconds": MODEL_TIMEOUT_SECONDS,
        }

    if status.get("state") == "running":
        if is_runtime_lock_interrupted():
            finished_at = now_msk()
            status.update({
                "state": "failed",
                "message": "Model interrupted because backend process stopped",
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "duration_seconds": get_status_duration_seconds(status, finished_at),
                "error": "Backend process was stopped before model finished; stale runtime lock was detected",
                "stale_lock_after_seconds": MODEL_TIMEOUT_SECONDS,
            })
            save_model_status(status)
            remove_stale_parser_lock(force=True)
            return status

        started_at = parse_msk_datetime(status.get("started_at"))
        if started_at:
            duration_seconds = max(0, int((now_msk() - started_at).total_seconds()))
            status["duration_seconds"] = duration_seconds
            status["message"] = "Model processing is running"
            status["stale_lock_after_seconds"] = MODEL_TIMEOUT_SECONDS

    return status


def load_model_status():
    try:
        return json.loads(MODEL_STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_model_running_status(started_at, limit):
    save_model_status({
        "state": "running",
        "message": "Model processing is running",
        "trigger": "manual",
        "requested_limit": limit or "all",
        "max_requests_per_run": "all",
        "model": MODEL_OPENROUTER_MODEL,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "stale_lock_after_seconds": MODEL_TIMEOUT_SECONDS,
    })


def save_model_finished_status(started_at, finished_at, result, limit):
    rate_limited = bool(result.get("rate_limited"))
    errors = int(result.get("errors") or 0)
    openrouter_usage = result.get("openrouter") or {}
    save_model_status({
        "state": "rate_limited" if rate_limited else "finished",
        "message": (
            "Model processing stopped because OpenRouter rate limit was reached"
            if rate_limited else "Model processing finished"
        ),
        "trigger": "manual",
        "requested_limit": limit or "all",
        "effective_limit": result.get("requested_limit"),
        "max_requests_per_run": result.get("max_requests_per_run", "all"),
        "model": result.get("model", MODEL_OPENROUTER_MODEL),
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "processed_items": result.get("processed_items"),
        "signals_created": result.get("signals_created"),
        "skipped": result.get("skipped", 0),
        "errors": errors,
        "rate_limited": rate_limited,
        "openrouter_run_cost": openrouter_usage.get("run_cost"),
        "openrouter": openrouter_usage,
        "stale_lock_after_seconds": MODEL_TIMEOUT_SECONDS,
    })


def save_model_failed_status(started_at, finished_at, error, limit):
    save_model_status({
        "state": "failed",
        "message": "Model processing failed",
        "trigger": "manual",
        "requested_limit": limit or "all",
        "max_requests_per_run": "all",
        "model": MODEL_OPENROUTER_MODEL,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "error": str(error),
        "stale_lock_after_seconds": MODEL_TIMEOUT_SECONDS,
    })


def save_model_status(status):
    MODEL_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def get_next_parser_run_at(current_time=None):
    current_time = current_time or now_msk()
    today = current_time.date()
    for hour in PARSER_SCHEDULE_HOURS:
        candidate = datetime.combine(today, datetime.min.time(), tzinfo=MSK_TZ).replace(hour=hour)
        if candidate > current_time:
            return candidate

    tomorrow = today + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=MSK_TZ).replace(
        hour=PARSER_SCHEDULE_HOURS[0]
    )


def get_parser_status():
    status = load_parser_status()
    if not status:
        return {
            "state": "idle",
            "message": "Parser has not been started yet",
            "stale_lock_after_seconds": PARSER_TIMEOUT_SECONDS,
        }

    if status.get("state") == "running":
        started_at = parse_msk_datetime(status.get("started_at"))
        if started_at:
            duration_seconds = max(0, int((now_msk() - started_at).total_seconds()))
            status["duration_seconds"] = duration_seconds
            status["message"] = "Parser is running"
            status["stale_lock_after_seconds"] = PARSER_TIMEOUT_SECONDS

    return status


def load_parser_status():
    try:
        return json.loads(PARSER_STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_parser_running_status(trigger, started_at):
    save_parser_status({
        "state": "running",
        "message": "Parser is running",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "stale_lock_after_seconds": PARSER_TIMEOUT_SECONDS,
    })


def save_parser_finished_status(trigger, started_at, finished_at, result):
    save_parser_status({
        "state": "finished",
        "message": "Parser finished",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "created": result.get("created"),
        "errors": result.get("errors"),
        "stale_lock_after_seconds": PARSER_TIMEOUT_SECONDS,
    })


def save_parser_failed_status(trigger, started_at, finished_at, error):
    save_parser_status({
        "state": "failed",
        "message": "Parser failed",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "error": str(error),
        "stale_lock_after_seconds": PARSER_TIMEOUT_SECONDS,
    })


def save_parser_progress_status(trigger, update_started_at, parser_started_at, event, source, index, total, result=None):
    progress = {
        "event": event,
        "source_index": index,
        "sources_total": total,
        "source_id": source["id"],
        "source_name": source["name"],
        "updated_at": now_msk().isoformat(timespec="seconds"),
    }
    if result is not None:
        progress["result"] = result

    status = load_parser_status() or {}
    status.update({
        "state": "running",
        "message": f"Parser is running: {source['name']} ({index}/{total})",
        "trigger": trigger,
        "started_at": parser_started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": max(0, int((now_msk() - parser_started_at).total_seconds())),
        "stale_lock_after_seconds": PARSER_TIMEOUT_SECONDS,
        "current_source": progress,
    })
    save_parser_status(status)

    update_status = load_update_status() or {}
    stages = update_status.get("stages") or {}
    parser_stage = stages.get("parser") if isinstance(stages.get("parser"), dict) else {}
    parser_stage.update({
        "state": "running",
        "message": status["message"],
        "started_at": parser_started_at.isoformat(timespec="seconds"),
        "duration_seconds": status["duration_seconds"],
        "current_source": progress,
    })
    stages["parser"] = parser_stage
    update_status.update({
        "state": "running",
        "message": status["message"],
        "trigger": trigger,
        "started_at": update_started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": max(0, int((now_msk() - update_started_at).total_seconds())),
        "stale_lock_after_seconds": UPDATE_TIMEOUT_SECONDS,
        "stages": stages,
    })
    save_update_status(update_status)


def save_parser_status(status):
    PARSER_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PARSER_STATUS_PATH.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def parse_msk_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=MSK_TZ)
    return parsed.astimezone(MSK_TZ)


def get_manual_update_cooldown_response():
    last_started = load_update_last_started()
    last_started_at = last_started.get("started_at") if last_started else None
    if not last_started_at:
        return None

    next_allowed_at = last_started_at + timedelta(seconds=UPDATE_MANUAL_COOLDOWN_SECONDS)
    current_time = now_msk()
    if current_time >= next_allowed_at:
        return None

    retry_after_seconds = max(1, int((next_allowed_at - current_time).total_seconds()))
    return {
        "status": "rate_limited",
        "message": "Manual update can be started only once every 60 minutes after any update start",
        "trigger": "manual",
        "last_started_at": last_started_at.isoformat(timespec="seconds"),
        "last_trigger": last_started.get("trigger"),
        "next_allowed_at": next_allowed_at.isoformat(timespec="seconds"),
        "retry_after_seconds": retry_after_seconds,
    }


def load_update_last_started():
    try:
        data = json.loads(UPDATE_LAST_START_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = load_legacy_manual_parser_started_data()

    raw_started_at = data.get("last_started_at")
    if not raw_started_at:
        return None

    try:
        parsed = datetime.fromisoformat(raw_started_at)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=MSK_TZ)
    else:
        parsed = parsed.astimezone(MSK_TZ)

    return {
        "started_at": parsed,
        "trigger": data.get("last_trigger") or data.get("trigger") or "unknown",
    }


def load_legacy_manual_parser_started_data():
    try:
        return json.loads(LEGACY_PARSER_MANUAL_THROTTLE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_update_started_at(started_at, trigger):
    UPDATE_LAST_START_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "last_started_at": started_at.isoformat(timespec="seconds"),
        "last_trigger": trigger,
        "manual_cooldown_seconds": UPDATE_MANUAL_COOLDOWN_SECONDS,
    }
    UPDATE_LAST_START_PATH.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )


def acquire_parser_lock(trigger):
    PARSER_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    remove_stale_parser_lock()

    try:
        lock_fd = os.open(str(PARSER_LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None

    lock_data = {
        "pid": os.getpid(),
        "boot_id": BOOT_ID,
        "trigger": trigger,
        "started_at": now_msk().isoformat(timespec="seconds"),
    }
    os.write(lock_fd, json.dumps(lock_data, ensure_ascii=False).encode("utf-8"))
    return lock_fd


def release_parser_lock(lock_fd):
    os.close(lock_fd)
    try:
        PARSER_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def remove_stale_parser_lock(force=False):
    try:
        lock_age_seconds = time.time() - PARSER_LOCK_PATH.stat().st_mtime
    except FileNotFoundError:
        return

    lock_data = load_lock_data()
    if force or is_lock_from_previous_process(lock_data):
        unlink_parser_lock()
        return

    if lock_age_seconds <= UPDATE_TIMEOUT_SECONDS:
        return

    pid = lock_data.get("pid") if isinstance(lock_data, dict) else None
    if pid and is_pid_running(pid):
        return

    unlink_parser_lock()


def unlink_parser_lock():
    try:
        PARSER_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def load_lock_data():
    try:
        return json.loads(PARSER_LOCK_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def is_runtime_lock_interrupted():
    lock_data = load_lock_data()
    if not lock_data:
        return True
    if is_lock_from_previous_process(lock_data):
        return True
    pid = lock_data.get("pid")
    return bool(pid) and not is_pid_running(pid)


def is_lock_from_previous_process(lock_data):
    if not isinstance(lock_data, dict) or not lock_data:
        return False

    lock_boot_id = lock_data.get("boot_id")
    if lock_boot_id:
        return lock_boot_id != BOOT_ID

    lock_started_at = parse_msk_datetime(lock_data.get("started_at"))
    if lock_started_at:
        return lock_started_at < BOOT_STARTED_AT

    return False


def is_pid_running(pid):
    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def start_parser_scheduler():
    global _scheduler_started
    with _scheduler_start_lock:
        if _scheduler_started:
            return
        _scheduler_started = True

    thread = threading.Thread(
        target=parser_scheduler_loop,
        name="parser-scheduler",
        daemon=True,
    )
    thread.start()


def parser_scheduler_loop():
    while True:
        try:
            next_run_at = get_next_parser_run_at()
            sleep_seconds = max(1, (next_run_at - now_msk()).total_seconds())
            time.sleep(sleep_seconds)

            result, status_code = start_update_job_background("auto")
            if status_code == 202:
                print(
                    f"Update auto started at {result['started_at']}",
                    flush=True,
                )
            else:
                print(
                    f"Update auto skipped at {now_msk().isoformat(timespec='seconds')}: "
                    f"{result.get('message')}",
                    flush=True,
                )
        except Exception as error:
            print(
                f"Update auto failed at {now_msk().isoformat(timespec='seconds')}: {error}",
                flush=True,
            )


start_parser_scheduler()


if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=False)
