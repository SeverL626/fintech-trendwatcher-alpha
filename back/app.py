import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request

try:
    from back.init_db import DB_PATH
except ModuleNotFoundError:
    from init_db import DB_PATH


MSK_TZ = ZoneInfo("Europe/Moscow")
PARSER_SCHEDULE_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
PARSER_PERIOD_HOURS = 3
PARSER_LOCK_PATH = Path(DB_PATH).parent / "parser.lock"
PARSER_MANUAL_COOLDOWN_SECONDS = 60 * 60
PARSER_MANUAL_THROTTLE_PATH = Path(DB_PATH).parent / "parser_manual_throttle.json"
PARSER_TIMEOUT_SECONDS = 60 * 60
PARSER_STATUS_PATH = Path(DB_PATH).parent / "parser_status.json"
MODEL_TIMEOUT_SECONDS = 60 * 60
MODEL_STATUS_PATH = Path(DB_PATH).parent / "model_status.json"
MODEL_OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it")
MODEL_MAX_REQUESTS_PER_RUN = None
UPDATE_TIMEOUT_SECONDS = 60 * 60
UPDATE_STATUS_PATH = Path(DB_PATH).parent / "update_status.json"

app = Flask(__name__)
app.config["DB_PATH"] = DB_PATH
app.json.ensure_ascii = False
app.json.compact = False

_scheduler_started = False
_scheduler_start_lock = threading.Lock()


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
    status = get_update_status()
    return jsonify({
        "ok": status.get("state") not in {"failed", "timed_out"},
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


def run_parser_from_db(db_path):
    try:
        from back.parser import run_parser_from_db as parser_runner
    except ModuleNotFoundError:
        from parser import run_parser_from_db as parser_runner

    return parser_runner(db_path)


def run_model_from_db(db_path, limit=None):
    try:
        from model.signal_processor import process_new_raw_news
    except ModuleNotFoundError:
        from signal_processor import process_new_raw_news

    return process_new_raw_news(db_path, limit)


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
        "timeout_minutes": PARSER_TIMEOUT_SECONDS // 60,
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
        "timeout_minutes": MODEL_TIMEOUT_SECONDS // 60,
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
        "timeout_minutes": UPDATE_TIMEOUT_SECONDS // 60,
        "stages": ["parser", "model"],
        "model_max_requests_per_run": "all",
        "next_run_at": get_next_parser_run_at(current_time).isoformat(timespec="seconds"),
        "manual_start": "/update",
        "status_url": "/update/status",
    }


def get_update_overview():
    return {
        "enabled": True,
        "timezone": "Europe/Moscow",
        "schedule": [f"{hour:02d}:00" for hour in PARSER_SCHEDULE_HOURS],
        "period_hours": PARSER_PERIOD_HOURS,
        "next_run_at": get_next_parser_run_at().isoformat(timespec="seconds"),
        "timeout_minutes": UPDATE_TIMEOUT_SECONDS // 60,
        "stages": [
            {
                "name": "parser",
                "description": "Collects new raw_news from active sources",
            },
            {
                "name": "model",
                "description": "Processes new raw_news into signals",
                "provider": "openrouter",
                "model": MODEL_OPENROUTER_MODEL,
                "max_requests_per_run": "all",
            },
        ],
        "manual_start": "/update",
        "status_url": "/update/status",
    }


def start_update_job_background(trigger):
    if trigger == "manual":
        cooldown_response = get_manual_parser_cooldown_response()
        if cooldown_response:
            cooldown_response["status_url"] = "/update/status"
            return cooldown_response, 429

    try:
        ensure_model_configured()
    except Exception as error:
        return {
            "status": "error",
            "message": str(error),
            "trigger": trigger,
            "status_url": "/update/status",
        }, 500

    lock_fd = acquire_parser_lock("update")
    if lock_fd is None:
        return {
            "status": "busy",
            "message": "Update is already running",
            "trigger": trigger,
            "status_url": "/update/status",
        }, 409

    started_at = now_msk()
    try:
        if trigger == "manual":
            save_manual_parser_started_at(started_at)
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
        print(
            f"Update {trigger} finished at {result['finished_at']} "
            f"with parser_created={parser_summary.get('created', 0)} "
            f"signals_created={model_summary.get('signals_created', 0)}",
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
        parser_result = run_parser_from_db(app.config["DB_PATH"])
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

    finished_at = now_msk()
    result = {
        "state": "finished",
        "message": "Update finished",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "timeout_seconds": UPDATE_TIMEOUT_SECONDS,
        "summary": {
            "parser": parser_summary,
            "model": model_summary,
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
            "timeout_seconds": UPDATE_TIMEOUT_SECONDS,
        }

    if status.get("state") == "running":
        started_at = parse_msk_datetime(status.get("started_at"))
        if started_at:
            duration_seconds = max(0, int((now_msk() - started_at).total_seconds()))
            status["duration_seconds"] = duration_seconds
            if duration_seconds > UPDATE_TIMEOUT_SECONDS:
                status["state"] = "timed_out"
                status["message"] = "Update exceeded the 1 hour timeout"
                status["timeout_seconds"] = UPDATE_TIMEOUT_SECONDS
                save_update_status(status)

    return status


def load_update_status():
    try:
        return json.loads(UPDATE_STATUS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_update_running_status(trigger, started_at):
    save_update_status({
        "state": "running",
        "message": "Update is running",
        "trigger": trigger,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": None,
        "duration_seconds": 0,
        "timeout_seconds": UPDATE_TIMEOUT_SECONDS,
        "summary": {},
        "stages": {
            "parser": {"state": "pending", "message": "Parser has not started yet"},
            "model": {"state": "pending", "message": "Model has not started yet"},
        },
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
        "timeout_seconds": UPDATE_TIMEOUT_SECONDS,
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
        "timeout_seconds": UPDATE_TIMEOUT_SECONDS,
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


def compact_stage_result(stage, result):
    if stage == "parser":
        return make_parser_stage_summary(result)
    if stage == "model":
        return make_model_stage_summary(result)
    return result


def get_model_status():
    status = load_model_status()
    if not status:
        return {
            "state": "idle",
            "message": "Model processing has not been started yet",
            "timeout_seconds": MODEL_TIMEOUT_SECONDS,
        }

    if status.get("state") == "running":
        started_at = parse_msk_datetime(status.get("started_at"))
        if started_at:
            duration_seconds = max(0, int((now_msk() - started_at).total_seconds()))
            status["duration_seconds"] = duration_seconds
            if duration_seconds > MODEL_TIMEOUT_SECONDS:
                status["state"] = "timed_out"
                status["message"] = "Model processing exceeded the 1 hour timeout"
                status["timeout_seconds"] = MODEL_TIMEOUT_SECONDS
                save_model_status(status)

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
        "timeout_seconds": MODEL_TIMEOUT_SECONDS,
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
        "timeout_seconds": MODEL_TIMEOUT_SECONDS,
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
        "timeout_seconds": MODEL_TIMEOUT_SECONDS,
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
            "timeout_seconds": PARSER_TIMEOUT_SECONDS,
        }

    if status.get("state") == "running":
        started_at = parse_msk_datetime(status.get("started_at"))
        if started_at:
            duration_seconds = max(0, int((now_msk() - started_at).total_seconds()))
            status["duration_seconds"] = duration_seconds
            if duration_seconds > PARSER_TIMEOUT_SECONDS:
                status["state"] = "timed_out"
                status["message"] = "Parser exceeded the 1 hour timeout"
                status["timeout_seconds"] = PARSER_TIMEOUT_SECONDS
                save_parser_status(status)

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
        "timeout_seconds": PARSER_TIMEOUT_SECONDS,
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
        "timeout_seconds": PARSER_TIMEOUT_SECONDS,
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
        "timeout_seconds": PARSER_TIMEOUT_SECONDS,
    })


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


def get_manual_parser_cooldown_response():
    last_started_at = load_manual_parser_started_at()
    if not last_started_at:
        return None

    next_allowed_at = last_started_at + timedelta(seconds=PARSER_MANUAL_COOLDOWN_SECONDS)
    current_time = now_msk()
    if current_time >= next_allowed_at:
        return None

    retry_after_seconds = max(1, int((next_allowed_at - current_time).total_seconds()))
    return {
        "status": "rate_limited",
        "message": "Manual parser can be started only once every 60 minutes",
        "trigger": "manual",
        "last_started_at": last_started_at.isoformat(timespec="seconds"),
        "next_allowed_at": next_allowed_at.isoformat(timespec="seconds"),
        "retry_after_seconds": retry_after_seconds,
    }


def load_manual_parser_started_at():
    try:
        data = json.loads(PARSER_MANUAL_THROTTLE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    raw_started_at = data.get("last_started_at")
    if not raw_started_at:
        return None

    try:
        parsed = datetime.fromisoformat(raw_started_at)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=MSK_TZ)
    return parsed.astimezone(MSK_TZ)


def save_manual_parser_started_at(started_at):
    PARSER_MANUAL_THROTTLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "last_started_at": started_at.isoformat(timespec="seconds"),
        "cooldown_seconds": PARSER_MANUAL_COOLDOWN_SECONDS,
    }
    PARSER_MANUAL_THROTTLE_PATH.write_text(
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


def remove_stale_parser_lock():
    try:
        lock_age_seconds = time.time() - PARSER_LOCK_PATH.stat().st_mtime
    except FileNotFoundError:
        return

    if lock_age_seconds <= UPDATE_TIMEOUT_SECONDS:
        return

    lock_data = load_lock_data()
    pid = lock_data.get("pid") if isinstance(lock_data, dict) else None
    if pid and is_pid_running(pid):
        return

    try:
        PARSER_LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def load_lock_data():
    try:
        return json.loads(PARSER_LOCK_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


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
