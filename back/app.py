import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

try:
    from back.init_db import DB_PATH
except ModuleNotFoundError:
    from init_db import DB_PATH


MSK_TZ = ZoneInfo("Europe/Moscow")
PARSER_SCHEDULE_HOURS = (6, 18)
PARSER_PERIOD_HOURS = 12
PARSER_LOCK_STALE_SECONDS = 6 * 60 * 60
PARSER_LOCK_PATH = Path(DB_PATH).parent / "parser.lock"

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
        "message": "Welcom to main page of the Alfa-HackItOn backend!",
        "current_time": {
            "timezone": "Europe/Moscow",
            "iso": now_msk().isoformat(timespec="seconds"),
        },
        "parser_update_settings": get_parser_update_settings(),
        "routes": ["/parser"],
    })


@app.route("/parser")
def run_parser():
    parser_result, status_code = run_parser_job("manual")
    return jsonify({
        "ok": status_code == 200,
        "parser": parser_result,
    }), status_code


def run_parser_from_db(db_path):
    try:
        from back.parser import run_parser_from_db as parser_runner
    except ModuleNotFoundError:
        from parser import run_parser_from_db as parser_runner

    return parser_runner(db_path)


def now_msk():
    return datetime.now(MSK_TZ)


def get_parser_update_settings():
    current_time = now_msk()
    return {
        "enabled": True,
        "timezone": "Europe/Moscow",
        "schedule": [f"{hour:02d}:00" for hour in PARSER_SCHEDULE_HOURS],
        "period_hours": PARSER_PERIOD_HOURS,
        "next_run_at": get_next_parser_run_at(current_time).isoformat(timespec="seconds"),
    }


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


def run_parser_job(trigger):
    lock_fd = acquire_parser_lock(trigger)
    if lock_fd is None:
        return {
            "status": "busy",
            "message": "Parser is already running",
            "trigger": trigger,
        }, 409

    started_at = now_msk()
    try:
        result = run_parser_from_db(app.config["DB_PATH"])
        result["trigger"] = trigger
        result["started_at"] = started_at.isoformat(timespec="seconds")
        result["finished_at"] = now_msk().isoformat(timespec="seconds")
        return result, 200
    finally:
        release_parser_lock(lock_fd)


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

    if lock_age_seconds > PARSER_LOCK_STALE_SECONDS:
        try:
            PARSER_LOCK_PATH.unlink()
        except FileNotFoundError:
            pass


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

            result, status_code = run_parser_job("auto")
            if status_code == 200:
                print(
                    f"Parser auto update finished at {result['finished_at']} "
                    f"with created={result.get('created', 0)} errors={result.get('errors', 0)}",
                    flush=True,
                )
            else:
                print(
                    f"Parser auto update skipped at {now_msk().isoformat(timespec='seconds')}: "
                    f"{result.get('message')}",
                    flush=True,
                )
        except Exception as error:
            print(
                f"Parser auto update failed at {now_msk().isoformat(timespec='seconds')}: {error}",
                flush=True,
            )


start_parser_scheduler()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
