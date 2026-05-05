import hashlib
import json
import re

try:
    from back.connectors import get_connector
    from back.connectors.base import BaseConnector, DEFAULT_LOOKBACK_DAYS, DEFAULT_USER_AGENT
    from back.init_db import DB_PATH, connect_db, init_db
except ModuleNotFoundError:
    from connectors import get_connector
    from connectors.base import BaseConnector, DEFAULT_LOOKBACK_DAYS, DEFAULT_USER_AGENT
    from init_db import DB_PATH, connect_db, init_db


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


def run_parser_from_db(db_path=DB_PATH):
    init_db(db_path, seed_initial_source=False)
    results = []

    with connect_db(db_path) as db:
        sources = db.execute("""
            SELECT id, name, url, source_type, parser_config
            FROM sources
            WHERE is_active = 1
            ORDER BY id ASC
        """).fetchall()

        for source in sources:
            try:
                result = parse_source(db, source)
            except Exception as error:
                result = source_error_result(source, error)
            results.append(result)

    return aggregate_parser_results(results)


def parse_source(db, source):
    config = load_parser_config(source["parser_config"])
    config["_existing_urls"] = load_existing_urls(db, source["id"])
    connector_name = config.get("connector") or source["source_type"]
    connector = get_connector(connector_name)
    items = connector.parse(source, config)
    market_stats = []
    if hasattr(connector, "parse_market_stats"):
        market_stats = connector.parse_market_stats(source, config)

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

    market_stats_created = 0
    for stat in market_stats:
        if insert_moex_daily_stat(db, source["id"], stat):
            market_stats_created += 1

    db.execute("UPDATE sources SET last_parsed_at = CURRENT_TIMESTAMP WHERE id = ?", (source["id"],))
    db.commit()

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "source_type": source["source_type"],
        "connector": connector_name,
        "found": len(items),
        "created": created,
        "market_stats_found": len(market_stats),
        "market_stats_created": market_stats_created,
        "duplicates": duplicates,
        "skipped": duplicates + skipped_quality,
        "skipped_quality": skipped_quality,
        "errors": 0,
        "empty": len(items) == 0 and len(market_stats) == 0,
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
        "duplicates": duplicates,
        "skipped": duplicates + skipped_quality,
        "skipped_quality": skipped_quality,
        "errors": errors,
        "empty_sources": empty_sources,
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
    if result.get("found", 0) == 0:
        if result.get("market_stats_found", 0):
            return (
                f"{result.get('source_name')} ({result.get('source_url')}): "
                f"статистики найдено {result.get('market_stats_found', 0)}, "
                f"сохранено {result.get('market_stats_created', 0)}"
            )
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
    config["max_age_days"] = DEFAULT_LOOKBACK_DAYS
    config["max_age_hours"] = DEFAULT_LOOKBACK_DAYS * 24
    return config


def normalize_news_item(item, config):
    if not item or not item.get("url"):
        return None

    title = clean_text(item.get("title"))
    text = clean_text(item.get("text"))
    published_at = item.get("published_at")

    if not DATE_VALIDATOR.is_recent(published_at, config):
        return None
    if looks_mojibake(title) or looks_mojibake(text):
        title = repair_mojibake(title)
        text = repair_mojibake(text)
    if not is_useful_text(title, text, config):
        return None

    normalized = dict(item)
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


def is_useful_text(title, text, config):
    if not text:
        return False
    if looks_mojibake(text):
        return False

    compact_title = compact_for_compare(title)
    compact_text = compact_for_compare(text)
    if compact_title and compact_title == compact_text:
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
    return existing is None


def insert_moex_daily_stat(db, source_id, stat):
    existing = db.execute("""
        SELECT id
        FROM moex_daily_stats
        WHERE source_id = ? AND trade_date = ?
    """, (
        source_id,
        stat.get("trade_date"),
    )).fetchone()

    db.execute("""
        INSERT INTO moex_daily_stats (
            source_id,
            trade_date,
            securities_count,
            traded_securities_count,
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, trade_date) DO UPDATE SET
            securities_count = excluded.securities_count,
            traded_securities_count = excluded.traded_securities_count,
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
        stat.get("trade_date"),
        stat.get("securities_count"),
        stat.get("traded_securities_count"),
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
        json.dumps(stat.get("raw_data") or stat, ensure_ascii=False),
    ))
    return existing is None


def make_content_hash(title, text):
    value = f"{title or ''}\n{text or ''}".strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps(run_parser_from_db(), ensure_ascii=False, indent=2))
