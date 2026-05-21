import hashlib
import json
import os
import re
import time

try:
    from back.connectors import get_connector
    from back.connectors.base import BaseConnector, DEFAULT_LOOKBACK_DAYS, DEFAULT_USER_AGENT
    from back.init_db import (
        DB_PATH,
        connect_db,
        init_db,
        detect_market_anomalies,
        insert_market_event,
        insert_moex_daily_stat,
        insert_moex_instrument_daily,
        update_moex_fetch_status,
    )
except ModuleNotFoundError:
    from connectors import get_connector
    from connectors.base import BaseConnector, DEFAULT_LOOKBACK_DAYS, DEFAULT_USER_AGENT
    from init_db import (
        DB_PATH,
        connect_db,
        init_db,
        detect_market_anomalies,
        insert_market_event,
        insert_moex_daily_stat,
        insert_moex_instrument_daily,
        update_moex_fetch_status,
    )


MIN_TEXT_LENGTH = 80
DATE_VALIDATOR = BaseConnector()
MOJIBAKE_MARKERS = (
    "Рџ",
    "Рќ",
    "Р Р",
    "РЎ",
    "СЃ",
    "С‚",
    "СЊ",
    "СЏ",
    "вЂ",
    "Ð",
    "Ñ",
    "�",
)


DEFAULT_PARSER_CONFIG = {
    "connector": "rbc",
    "max_age_days": DEFAULT_LOOKBACK_DAYS,
    "max_age_hours": 24,
    "strict_dates": True,
    "max_future_hours": 2,
    "min_text_length": MIN_TEXT_LENGTH,
    "timeout": 15,
    "user_agent": DEFAULT_USER_AGENT,
    "verify_ssl": True,
}

PARSER_ONLY_SOURCE_IDS = tuple(
    int(value)
    for value in re.findall(r"\d+", os.getenv("PARSER_ONLY_SOURCE_IDS", ""))
)


def run_parser_from_db(db_path=DB_PATH, progress_callback=None):
    init_db(db_path, seed_initial_source=True)
    results = []

    with connect_db(db_path) as db:
        query = """
            SELECT id, name, url, source_type, parser_config
            FROM sources
            WHERE is_active = 1
            ORDER BY id ASC
        """
        params = ()
        if PARSER_ONLY_SOURCE_IDS:
            placeholders = ",".join("?" for _ in PARSER_ONLY_SOURCE_IDS)
            query = query.replace(
                "WHERE is_active = 1",
                f"WHERE is_active = 1 AND id IN ({placeholders})",
            )
            params = PARSER_ONLY_SOURCE_IDS
        sources = db.execute(query, params).fetchall()

        total_sources = len(sources)
        for index, source in enumerate(sources, start=1):
            if progress_callback:
                progress_callback("started", source, index, total_sources)
            try:
                result = parse_source(db, source)
            except Exception as error:
                result = source_error_result(source, error)
            results.append(result)
            if progress_callback:
                progress_callback("finished", source, index, total_sources, result)

    return aggregate_parser_results(results)


def parse_source(db, source):
    started_at = time.monotonic()
    config = load_parser_config(source["parser_config"])
    config["_existing_urls"] = load_existing_urls(db, source["id"])

    connector_name = config.get("connector") or source["source_type"]
    connector = get_connector(connector_name)

    if connector_name == "moex":
        return parse_moex_source(db, source, connector, config, started_at)

    items = connector.parse(source, config)

    created = 0
    duplicates = 0
    skipped_quality = 0

    for item in items:
        normalized_item = normalize_news_item(item, config)
        if not normalized_item:
            skipped_quality += 1
            continue

        if insert_raw_news(db, source["id"], normalized_item):
            created += 1
        else:
            duplicates += 1

    db.execute(
        "UPDATE sources SET last_parsed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (source["id"],),
    )
    db.commit()

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "source_type": source["source_type"],
        "connector": connector_name,
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "found": len(items),
        "created": created,
        "market_stats_found": 0,
        "market_stats_created": 0,
        "moex_instruments_found": 0,
        "moex_instruments_created": 0,
        "market_events_found": 0,
        "market_events_created": 0,
        "duplicates": duplicates,
        "skipped": duplicates + skipped_quality,
        "skipped_quality": skipped_quality,
        "errors": 0,
        "empty": len(items) == 0,
    }

def parse_moex_source(db, source, connector, config, started_at):
    market_instruments = []

    if hasattr(connector, "parse_market_instruments"):
        market_instruments = connector.parse_market_instruments(source, config)

    market_stats = []
    if market_instruments and hasattr(connector, "aggregate_daily_stats"):
        fallback_date = market_instruments[0].get("trade_date")
        market_stats = [
            connector.aggregate_daily_stats(market_instruments, fallback_date)
        ]

    moex_instruments_created = 0
    market_stats_created = 0
    market_events_created = 0
    anomalies = []

    for instr in market_instruments:
        if insert_moex_instrument_daily(
            db,
            trade_date=instr.get("trade_date"),
            secid=instr.get("secid"),
            boardid=instr.get("boardid"),
            shortname=instr.get("shortname"),
            secname=instr.get("secname"),
            last=instr.get("last"),
            open_price=instr.get("open"),
            high=instr.get("high"),
            low=instr.get("low"),
            marketprice=instr.get("marketprice"),
            value_rub=instr.get("value_rub", instr.get("value")),
            value_usd=instr.get("value_usd"),
            volume=instr.get("volume"),
            numtrades=instr.get("numtrades"),
            change_percent=instr.get("change_percent"),
            raw_data=instr.get("raw_data"),
        ):
            moex_instruments_created += 1

    for stat in market_stats:
        stat["source_id"] = source["id"]
        if insert_moex_daily_stat(db, source["id"], stat):
            market_stats_created += 1

    if market_stats:
        trade_date = market_stats[0].get("trade_date")

        anomalies = detect_market_anomalies(db, trade_date)
        for anomaly in anomalies:
            if insert_market_event(db, anomaly):
                market_events_created += 1

    update_moex_fetch_status(db, success=True)
    db.execute(
        "UPDATE sources SET last_parsed_at = CURRENT_TIMESTAMP WHERE id = ?",
        (source["id"],),
    )
    db.commit()

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "source_type": source["source_type"],
        "connector": "moex",
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "found": 0,
        "created": 0,
        "market_stats_found": len(market_stats),
        "market_stats_created": market_stats_created,
        "moex_instruments_found": len(market_instruments),
        "moex_instruments_created": moex_instruments_created,
        "market_events_found": len(anomalies) if market_stats else 0,
        "market_events_created": market_events_created,
        "duplicates": 0,
        "skipped": 0,
        "skipped_quality": 0,
        "errors": 0,
        "empty": len(market_instruments) == 0 and len(market_stats) == 0,
    }


def load_existing_urls(db, source_id):
    return {
        row["url"]
        for row in db.execute(
            "SELECT url FROM raw_news WHERE source_id = ?",
            (source_id,),
        )
    }


def aggregate_parser_results(results):
    errors = sum(1 for item in results if item.get("error"))
    empty_sources = sum(
        1
        for item in results
        if (
            not item.get("error")
            and item.get("found", 0) == 0
            and item.get("market_stats_found", 0) == 0
        )
    )
    duplicates = sum(item.get("duplicates", item.get("skipped", 0)) for item in results)
    skipped_quality = sum(item.get("skipped_quality", 0) for item in results)
    return {
        "sources": len(results),
        "created": sum(item["created"] for item in results),
        "market_stats_created": sum(item.get("market_stats_created", 0) for item in results),
        "moex_instruments_found": sum(item.get("moex_instruments_found", 0) for item in results),
        "moex_instruments_created": sum(item.get("moex_instruments_created", 0) for item in results),
        "market_events_found": sum(item.get("market_events_found", 0) for item in results),
        "market_events_created": sum(item.get("market_events_created", 0) for item in results),
        "duplicates": duplicates,
        "skipped": duplicates + skipped_quality,
        "skipped_quality": skipped_quality,
        "errors": errors,
        "empty_sources": empty_sources,
        "duration_seconds": round(sum(item.get("duration_seconds", 0) for item in results), 3),
        "slow_sources": [
            {
                "source_id": item.get("source_id"),
                "source_name": item.get("source_name"),
                "duration_seconds": item.get("duration_seconds", 0),
            }
            for item in sorted(results, key=lambda item: item.get("duration_seconds", 0), reverse=True)[:5]
            if item.get("duration_seconds")
        ],
        "summary": [
            format_source_summary(item)
            for item in results
        ],
        "results": results,
    }


def source_error_result(source, error):
    config = load_parser_config(source["parser_config"])
    connector_name = config.get("connector") or source["source_type"]
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "source_type": source["source_type"],
        "connector": connector_name,
        "found": 0,
        "created": 0,
        "market_stats_found": 0,
        "market_stats_created": 0,
        "moex_instruments_found": 0,
        "moex_instruments_created": 0,
        "market_events_found": 0,
        "market_events_created": 0,
        "duplicates": 0,
        "skipped": 0,
        "errors": 1,
        "empty": False,
        "error": str(error),
    }

def format_source_summary(result):
    if result.get("error"):
        return (
            f"{result.get('source_name')} ({result.get('source_url')}): "
            f"ошибка: {result.get('error')}"
        )

    if result.get("connector") == "moex":
        return (
            f"{result.get('source_name')} ({result.get('source_url')}): "
            f"инструментов найдено {result.get('moex_instruments_found', 0)}, "
            f"инструментов сохранено {result.get('moex_instruments_created', 0)}, "
            f"snapshot сохранено {result.get('market_stats_created', 0)}, "
            f"аномалий найдено {result.get('market_events_found', 0)}, "
            f"аномалий сохранено {result.get('market_events_created', 0)}"
        )

    if result.get("found", 0) == 0:
        return (
            f"{result.get('source_name')} ({result.get('source_url')}): "
            "ничего не найдено"
        )

    return (
        f"{result.get('source_name')} ({result.get('source_url')}): "
        f"найдено {result.get('found', 0)}, "
        f"сохранено {result.get('created', 0)}, "
        f"дублей {result.get('duplicates', 0)}, "
        f"отфильтровано {result.get('skipped_quality', 0)}"
    )


def load_parser_config(raw_config):
    config = dict(DEFAULT_PARSER_CONFIG)
    if raw_config:
        loaded_config = json.loads(raw_config)
        if not isinstance(loaded_config, dict):
            raise ValueError("parser_config must be a JSON object")
        config.update(loaded_config)
    config["max_age_days"] = int(config.get("max_age_days") or DEFAULT_LOOKBACK_DAYS)
    if config.get("max_age_hours") is None:
        config["max_age_hours"] = config["max_age_days"] * 24
    else:
        config["max_age_hours"] = int(config["max_age_hours"])
    return config

def is_telegram_item(item):
    raw_data = item.get("raw_data") or {}

    return (
        item.get("adapter") == "telegram"
        or raw_data.get("adapter") == "telegram"
        or raw_data.get("fallback_adapter") == "telegram"
        or raw_data.get("text_source") == "official_telegram"
        or str(item.get("source_url", "")).startswith("https://t.me/")
        or str(raw_data.get("source_url", "")).startswith("https://t.me/")
        or str(raw_data.get("fallback_source_url", "")).startswith("https://t.me/")
    )

def normalize_news_item(item, config):
    if not item or not item.get("url"):
        return None

    title = clean_text(item.get("title"))
    text = clean_text(item.get("text"))
    published_at = item.get("published_at")
    is_telegram = is_telegram_item(item)

    if not DATE_VALIDATOR.is_recent(published_at, config):
        return None

    if looks_mojibake(title) or looks_mojibake(text):
        title = repair_mojibake(title)
        text = repair_mojibake(text)

    if not is_useful_text(title, text, config, allow_title_equals_text=is_telegram):
        return None

    normalized = dict(item)

    if is_telegram:
        # Для Telegram вообще не сохраняем title
        normalized["title"] = None
        normalized["text"] = text
    else:
        # Для сайтов оставляем старую логику
        normalized["title"] = title
        normalized["text"] = remove_title_prefix(text, title)

    normalized["published_at"] = published_at
    return normalized


def clean_text(value):
    return re.sub(r"[ \t\r\f\v]+", " ", str(value or "")).strip()


def repair_mojibake(value):
    if not value:
        return value
    try:
        repaired = value.encode("cp1251").decode("utf-8")
    except UnicodeError:
        return value
    return clean_text(repaired) if repaired else value


def looks_mojibake(value):
    text = str(value or "")
    return any(marker in text for marker in MOJIBAKE_MARKERS)


def is_useful_text(title, text, config, allow_title_equals_text=False):
    if not text:
        return False

    if looks_mojibake(text):
        return False

    compact_title = compact_for_compare(title)
    compact_text = compact_for_compare(text)

    if compact_title and compact_title == compact_text and not allow_title_equals_text:
        return False

    min_text_length = int(config.get("min_text_length") or MIN_TEXT_LENGTH)
    if len(text) < min_text_length:
        return False

    return True


def remove_title_prefix(text, title):
    if not title:
        return text
    compact_title = compact_for_compare(title)
    compact_text = compact_for_compare(text)
    if not compact_title or not compact_text.startswith(compact_title):
        return text

    remainder = text[len(title):].lstrip(" .:-\n")
    if len(remainder) >= MIN_TEXT_LENGTH:
        return remainder
    return text


def compact_for_compare(value):
    return re.sub(r"\W+", "", str(value or "").casefold())


def insert_raw_news(db, source_id, item):
    existing = db.execute(
        "SELECT id FROM raw_news WHERE url = ?",
        (item["url"],),
    ).fetchone()
    cursor = db.execute("""
        INSERT INTO raw_news (
            source_id,
            url,
            title,
            text,
            published_at,
            content_hash,
            raw_data,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            title = COALESCE(excluded.title, raw_news.title),
            text = CASE
                WHEN raw_news.text LIKE '%Ð%'
                  OR raw_news.text LIKE '%Ñ%'
                  OR raw_news.text LIKE '%Â%'
                  OR raw_news.text LIKE '%�%'
                THEN excluded.text
                WHEN excluded.raw_data LIKE '%"adapter": "minfin"%'
                THEN excluded.text
                WHEN LENGTH(excluded.text) > LENGTH(raw_news.text)
                THEN excluded.text
                ELSE raw_news.text
            END,
            published_at = COALESCE(excluded.published_at, raw_news.published_at),
            content_hash = CASE
                WHEN raw_news.text LIKE '%Ð%'
                  OR raw_news.text LIKE '%Ñ%'
                  OR raw_news.text LIKE '%Â%'
                  OR raw_news.text LIKE '%�%'
                THEN excluded.content_hash
                WHEN excluded.raw_data LIKE '%"adapter": "minfin"%'
                THEN excluded.content_hash
                WHEN LENGTH(excluded.text) > LENGTH(raw_news.text)
                THEN excluded.content_hash
                ELSE raw_news.content_hash
            END,
            raw_data = CASE
                WHEN raw_news.text LIKE '%Ð%'
                  OR raw_news.text LIKE '%Ñ%'
                  OR raw_news.text LIKE '%Â%'
                  OR raw_news.text LIKE '%�%'
                THEN excluded.raw_data
                WHEN excluded.raw_data LIKE '%"adapter": "minfin"%'
                THEN excluded.raw_data
                WHEN LENGTH(excluded.text) > LENGTH(raw_news.text)
                THEN excluded.raw_data
                ELSE raw_news.raw_data
            END
    """, (
        source_id,
        item["url"],
        item.get("title"),
        item["text"],
        item.get("published_at"),
        make_content_hash(item.get("title"), item["text"]),
        json.dumps(item.get("raw_data") or item, ensure_ascii=False),
        "new",
    ))
    if existing is not None:
        return None
    return cursor.lastrowid


def make_content_hash(title, text):
    value = f"{title or ''}\n{text or ''}".strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps(run_parser_from_db(), ensure_ascii=False, indent=2))
