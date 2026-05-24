from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    from back.init_db import DB_PATH, connect_db, ensure_weekly_digest_schema
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db, ensure_weekly_digest_schema


MSK_TZ = ZoneInfo("Europe/Moscow")
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it")
OPENROUTER_TIMEOUT_SECONDS = 90
OPENROUTER_MAX_RETRIES = 3
OPENROUTER_RETRY_SECONDS = 20
TOP_NEWS_LIMIT = 15
PROMPT_VERSION = "weekly_digest_v2"


DIGEST_SYSTEM_PROMPT = """
Ты — аналитик Red Cat Trendwatcher для финтеха и банковского рынка.

Сделай полезный недельный дайджест для банка на русском языке.
У тебя есть топ-15 сигналов недели без дублей.

Требования:
- не выдумывай факты;
- не пересказывай каждую новость отдельно, группируй по смысловым темам;
- пиши коротко, конкретно и прикладно для банка;
- обязательно покажи: что произошло, почему важно, какие возможности/риски видны;
- не используй id новостей в тексте;
- верни только валидный JSON без markdown-обертки.
- не добавляй поля вне схемы.

Формат JSON:
{
  "title": "заголовок дайджеста 5-9 слов",
  "summary": "2-3 предложения с главным выводом недели",
  "sections": [
    {
      "title": "название темы",
      "what_happened": ["1-3 коротких факта"],
      "bank_meaning": "практический смысл для банка",
      "risks": "риски или ограничения; если их мало, напиши коротко",
      "actions": ["1-2 прикладных вывода"]
    }
  ],
  "final_takeaway": "короткий итог недели"
}
""".strip()


class WeeklyDigestError(RuntimeError):
    pass


class OpenRouterRateLimitError(WeeklyDigestError):
    pass


class OpenRouterRequestError(WeeklyDigestError):
    pass


def now_msk() -> datetime:
    return datetime.now(MSK_TZ)


def start_of_week(value: date) -> date:
    return value - timedelta(days=value.weekday())


def end_of_week(week_start: date) -> date:
    return week_start + timedelta(days=6)


def latest_finished_week(current_time: datetime | None = None) -> tuple[date, date]:
    current_time = normalize_datetime(current_time) or now_msk()
    current_week_start = start_of_week(current_time.date())
    week_start = current_week_start - timedelta(days=7)
    return week_start, end_of_week(week_start)


def normalize_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        parsed = parse_datetime_text(text)
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(MSK_TZ)


def parse_datetime_text(text: str) -> datetime | None:
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_openrouter_api_key() -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise WeeklyDigestError("OPENROUTER_API_KEY is not set")
    return api_key


def parse_signal_source_ids(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, int):
        return [value]
    return [int(part) for part in re.findall(r"\d+", str(value))]


def coerce_float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def signal_score(row) -> float:
    hotness = coerce_float(row.get("hotness"), -1.0)
    if hotness >= 0:
        return hotness
    scores = [
        coerce_float(row.get("scale_score"), -1.0),
        coerce_float(row.get("urgency_score"), -1.0),
        coerce_float(row.get("rigidity_score"), -1.0),
    ]
    scores = [score for score in scores if score >= 0]
    return sum(scores) / len(scores) if scores else -1.0


def load_raw_news_by_ids(connection: sqlite3.Connection, raw_news_ids: list[int]) -> dict[int, dict]:
    if not raw_news_ids:
        return {}
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
    return {int(row["id"]): dict(row) for row in rows}


def pick_signal_event_time(raw_rows: list[dict], signal_row: dict) -> datetime | None:
    dates = [
        normalize_datetime(row.get("published_at") or row.get("parsed_at"))
        for row in raw_rows
    ]
    dates = [item for item in dates if item is not None]
    if dates:
        return max(dates)
    return normalize_datetime(signal_row.get("created_at"))


def select_weekly_top_news(connection: sqlite3.Connection, week_start: date, week_end: date, limit: int = TOP_NEWS_LIMIT) -> list[dict]:
    rows = connection.execute("""
        SELECT
            id,
            headline,
            summary,
            why_now,
            category,
            sources,
            hotness,
            scale_score,
            urgency_score,
            rigidity_score,
            created_at
        FROM signals
        WHERE COALESCE(is_duplicate, 0) = 0
          AND COALESCE(is_fintech, 0) = 1
          AND TRIM(COALESCE(summary, '')) != ''
    """).fetchall()

    all_raw_ids = []
    signal_rows = []
    for row in rows:
        signal = dict(row)
        raw_ids = parse_signal_source_ids(signal.get("sources"))
        signal["raw_news_ids"] = raw_ids
        all_raw_ids.extend(raw_ids)
        signal_rows.append(signal)

    raw_by_id = load_raw_news_by_ids(connection, sorted(set(all_raw_ids)))
    selected = []
    for signal in signal_rows:
        raw_rows = [raw_by_id[raw_id] for raw_id in signal["raw_news_ids"] if raw_id in raw_by_id]
        event_time = pick_signal_event_time(raw_rows, signal)
        if not event_time:
            continue
        if not (week_start <= event_time.date() <= week_end):
            continue

        source_names = []
        urls = []
        for raw_row in raw_rows:
            source_name = str(raw_row.get("source_name") or "").strip()
            url = str(raw_row.get("url") or "").strip()
            if source_name and source_name not in source_names:
                source_names.append(source_name)
            if url and url not in urls:
                urls.append(url)

        selected.append({
            "id": int(signal["id"]),
            "headline": signal.get("headline") or "",
            "summary": signal.get("summary") or "",
            "why_now": signal.get("why_now") or "",
            "category": signal.get("category") or "",
            "hotness": round(signal_score(signal), 2),
            "scale_score": coerce_float(signal.get("scale_score"), None),
            "urgency_score": coerce_float(signal.get("urgency_score"), None),
            "rigidity_score": coerce_float(signal.get("rigidity_score"), None),
            "published_at": event_time.isoformat(timespec="seconds"),
            "source_names": source_names,
            "urls": urls[:3],
        })

    selected.sort(
        key=lambda item: (
            item["hotness"],
            item["published_at"],
            item["id"],
        ),
        reverse=True,
    )
    return selected[:limit]


def build_prompt(week_start: date, week_end: date, news: list[dict]) -> str:
    payload = {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "news": news,
    }
    return (
        f"{DIGEST_SYSTEM_PROMPT}\n\n"
        "Входные данные JSON:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def post_openrouter_with_retries(payload: dict) -> tuple[dict, dict]:
    api_key = get_openrouter_api_key()
    last_response = None
    for attempt in range(OPENROUTER_MAX_RETRIES + 1):
        response = requests.post(
            OPENROUTER_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://127.0.0.1:5000"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "Red Cat Trendwatcher"),
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT_SECONDS,
        )
        if response.status_code != 429:
            handle_openrouter_http_error(response)
            body = response.json()
            return body, normalize_openrouter_usage(body.get("usage"))

        last_response = response
        if attempt >= OPENROUTER_MAX_RETRIES:
            break
        time.sleep(parse_retry_after(response) or OPENROUTER_RETRY_SECONDS * (attempt + 1))

    raise OpenRouterRateLimitError(format_openrouter_error(last_response))


def handle_openrouter_http_error(response) -> None:
    if response.status_code == 429:
        raise OpenRouterRateLimitError(format_openrouter_error(response))
    if response.status_code >= 400:
        raise OpenRouterRequestError(format_openrouter_error(response))


def format_openrouter_error(response) -> str:
    if response is None:
        return "OpenRouter request failed"
    body = response.text[:1000] if response.text else ""
    return f"OpenRouter API HTTP {response.status_code}: {body}".strip()


def parse_retry_after(response) -> int | None:
    value = response.headers.get("Retry-After") if response is not None else None
    if not value:
        return None
    try:
        return max(1, int(float(value)))
    except (TypeError, ValueError):
        return None


def normalize_openrouter_usage(usage) -> dict:
    if not isinstance(usage, dict):
        return {}
    return {
        key: usage[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost", "cost_usd")
        if key in usage
    }


def get_usage_cost(usage) -> float:
    if not isinstance(usage, dict):
        return 0.0
    return coerce_float(usage.get("cost"), 0.0) or coerce_float(usage.get("cost_usd"), 0.0)


def extract_openrouter_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise WeeklyDigestError("OpenRouter response does not contain choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text") or ""))
        text = "".join(text_parts).strip()
        if text:
            return text
    raise WeeklyDigestError("OpenRouter response does not contain text content")


def parse_digest_response(text: str) -> dict:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            return fallback_digest_response(text)
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return fallback_digest_response(text)

    if not isinstance(parsed, dict):
        return fallback_digest_response(text)
    report = build_report_from_structured_response(parsed)
    return {
        "title": clean_text(parsed.get("title")) or "Недельный дайджест Red Cat",
        "summary": clean_text(parsed.get("summary")),
        "moex_summary": "",
        "report": report or clean_text(parsed.get("report")) or text.strip(),
    }


def fallback_digest_response(text: str) -> dict:
    clean = text.strip()
    first_line = next((line.strip("# ").strip() for line in clean.splitlines() if line.strip()), "")
    return {
        "title": first_line[:120] or "Недельный дайджест Red Cat",
        "summary": "",
        "moex_summary": "",
        "report": clean,
    }


def build_report_from_structured_response(parsed: dict) -> str:
    lines = []
    sections = parsed.get("sections") or []
    if isinstance(sections, dict):
        sections = [sections]
    if not isinstance(sections, list):
        sections = []

    for section in sections[:6]:
        if not isinstance(section, dict):
            continue
        title = clean_text(section.get("title"))
        if title:
            lines.append(f"## {title}")

        facts = normalize_text_list(section.get("what_happened"))
        if facts:
            lines.append("Что произошло")
            lines.extend(f"- {fact}" for fact in facts[:4])

        bank_meaning = clean_text(section.get("bank_meaning"))
        if bank_meaning:
            lines.append("Почему важно для банка")
            lines.append(bank_meaning)

        risks = clean_text(section.get("risks"))
        if risks:
            lines.append("Риски")
            lines.append(risks)

        actions = normalize_text_list(section.get("actions"))
        if actions:
            lines.append("Что учесть")
            lines.extend(f"- {action}" for action in actions[:3])

    final_takeaway = clean_text(parsed.get("final_takeaway"))
    if final_takeaway:
        lines.append("## Итог недели")
        lines.append(final_takeaway)

    return "\n".join(line for line in lines if line).strip()


def normalize_text_list(value) -> list[str]:
    if isinstance(value, str):
        parts = [part.strip(" -•\t") for part in re.split(r"\n+", value) if part.strip()]
        return parts or [value.strip()]
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        text = clean_text(item)
        if text:
            result.append(text)
    return result


def clean_text(value) -> str:
    return str(value or "").strip()


def build_weekly_digest(news: list[dict], week_start: date, week_end: date) -> tuple[dict, dict]:
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": build_prompt(week_start, week_end, news),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 3200,
    }
    response_payload, usage = post_openrouter_with_retries(payload)
    text = extract_openrouter_text(response_payload)
    digest = parse_digest_response(text)
    if not digest["report"]:
        raise WeeklyDigestError("Weekly digest model returned an empty report")
    return digest, usage


def insert_weekly_digest(
    connection: sqlite3.Connection,
    *,
    week_start: date,
    week_end: date,
    digest: dict,
    news_ids: list[int],
) -> int:
    cursor = connection.execute("""
        INSERT INTO weekly_digests (
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
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (
        week_start.isoformat(),
        week_end.isoformat(),
        digest.get("title") or "",
        digest.get("summary") or "",
        digest.get("report") or "",
        digest.get("moex_summary") or "",
        json.dumps(news_ids, ensure_ascii=False),
        OPENROUTER_MODEL,
        PROMPT_VERSION,
    ))
    return int(cursor.lastrowid)


def list_existing_digest_weeks(connection: sqlite3.Connection) -> set[date]:
    rows = connection.execute("""
        SELECT week_start
        FROM weekly_digests
        WHERE week_start IS NOT NULL AND TRIM(week_start) != ''
    """).fetchall()
    result = set()
    for row in rows:
        try:
            result.add(date.fromisoformat(str(row["week_start"])[:10]))
        except ValueError:
            continue
    return result


def list_finished_signal_weeks(connection: sqlite3.Connection, current_time=None) -> list[date]:
    current_time = normalize_datetime(current_time) or now_msk()
    current_week_start = start_of_week(current_time.date())
    rows = connection.execute("""
        SELECT id, sources, created_at
        FROM signals
        WHERE COALESCE(is_duplicate, 0) = 0
          AND COALESCE(is_fintech, 0) = 1
          AND TRIM(COALESCE(summary, '')) != ''
    """).fetchall()

    signal_rows = []
    raw_ids = []
    for row in rows:
        signal = dict(row)
        signal["raw_news_ids"] = parse_signal_source_ids(signal.get("sources"))
        raw_ids.extend(signal["raw_news_ids"])
        signal_rows.append(signal)

    raw_by_id = load_raw_news_by_ids(connection, sorted(set(raw_ids)))
    weeks = set()
    for signal in signal_rows:
        raw_rows = [raw_by_id[raw_id] for raw_id in signal["raw_news_ids"] if raw_id in raw_by_id]
        event_time = pick_signal_event_time(raw_rows, signal)
        if not event_time:
            continue
        week_start = start_of_week(event_time.date())
        if week_start < current_week_start:
            weeks.add(week_start)
    return sorted(weeks)


def generate_digest_for_week(
    connection: sqlite3.Connection,
    week_start: date,
    week_end: date,
    *,
    force=False,
) -> dict:
    existing = connection.execute(
        "SELECT id, prompt_version FROM weekly_digests WHERE week_start = ?",
        (week_start.isoformat(),),
    ).fetchone()
    if existing and not force and existing["prompt_version"] == PROMPT_VERSION:
        return {
            "created": 0,
            "skipped_existing": 1,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "digest_id": existing["id"],
            "news_selected": 0,
            "run_cost": 0.0,
        }

    news = select_weekly_top_news(connection, week_start, week_end, TOP_NEWS_LIMIT)
    if not news:
        return {
            "created": 0,
            "skipped_empty": 1,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "news_selected": 0,
            "run_cost": 0.0,
        }

    digest, usage = build_weekly_digest(news, week_start, week_end)

    if existing and (force or existing["prompt_version"] != PROMPT_VERSION):
        connection.execute(
            "DELETE FROM weekly_digests WHERE week_start = ?",
            (week_start.isoformat(),),
        )
    digest_id = insert_weekly_digest(
        connection,
        week_start=week_start,
        week_end=week_end,
        digest=digest,
        news_ids=[item["id"] for item in news],
    )
    connection.commit()

    return {
        "created": 1,
        "skipped_existing": 0,
        "skipped_empty": 0,
        "digest_id": digest_id,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "news_selected": len(news),
        "model": OPENROUTER_MODEL,
        "prompt_version": PROMPT_VERSION,
        "openrouter": usage,
        "run_cost": round(get_usage_cost(usage), 8),
    }


def generate_weekly_digest(db_path=DB_PATH, *, current_time=None, force=False) -> dict:
    week_start, week_end = latest_finished_week(current_time)
    with connect_db(db_path) as connection:
        ensure_weekly_digest_schema(connection)
        return generate_digest_for_week(connection, week_start, week_end, force=force)


def generate_missing_weekly_digests(db_path=DB_PATH, *, current_time=None, force=False) -> dict:
    current_time = normalize_datetime(current_time) or now_msk()
    with connect_db(db_path) as connection:
        ensure_weekly_digest_schema(connection)
        existing_weeks = list_existing_digest_weeks(connection)
        first_run = not existing_weeks
        if first_run:
            target_weeks = list_finished_signal_weeks(connection, current_time)
            mode = "backfill"
        else:
            target_weeks = [latest_finished_week(current_time)[0]]
            mode = "latest_week"

        created_items = []
        skipped_existing = []
        skipped_empty = []
        errors = []
        run_cost = 0.0
        news_selected = 0

        for week_start in target_weeks:
            week_end = end_of_week(week_start)
            try:
                result = generate_digest_for_week(connection, week_start, week_end, force=force)
            except Exception as error:
                connection.rollback()
                errors.append({
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "error": str(error),
                })
                continue

            run_cost += coerce_float(result.get("run_cost"), 0.0)
            news_selected += int(result.get("news_selected") or 0)
            if result.get("created"):
                created_items.append(result)
            elif result.get("skipped_existing"):
                skipped_existing.append(week_start.isoformat())
            elif result.get("skipped_empty"):
                skipped_empty.append(week_start.isoformat())

    latest_week_start, latest_week_end = latest_finished_week(current_time)
    return {
        "mode": mode,
        "first_run": first_run,
        "checked_weeks": len(target_weeks),
        "created": len(created_items),
        "created_items": created_items,
        "skipped_existing": len(skipped_existing),
        "skipped_existing_weeks": skipped_existing,
        "skipped_empty": len(skipped_empty),
        "skipped_empty_weeks": skipped_empty,
        "errors": len(errors),
        "error_items": errors,
        "week_start": latest_week_start.isoformat(),
        "week_end": latest_week_end.isoformat(),
        "news_selected": news_selected,
        "model": OPENROUTER_MODEL,
        "prompt_version": PROMPT_VERSION,
        "run_cost": round(run_cost, 8),
    }


if __name__ == "__main__":
    print(json.dumps(generate_weekly_digest(), ensure_ascii=False, indent=2))
