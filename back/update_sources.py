import json

try:
    from back.init_db import DB_PATH, connect_db, init_db
    from back.parser import DEFAULT_PARSER_CONFIG, NewsParser
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db, init_db
    from parser import DEFAULT_PARSER_CONFIG, NewsParser


def main():
    source = ask_source()
    config = ask_parser_config()

    print("\nParser config:")
    print(json.dumps(config, ensure_ascii=False, indent=2))

    print("\nTesting source...")
    found = test_source(source["url"], config)
    print(f"Found: {len(found)}")
    for item in found[:5]:
        print(f"- {item.get('title')} | {item.get('published_at')}")

    if not confirm("\nSave source?"):
        print("Not saved.")
        return

    source_id = save_source(DB_PATH, source, config)
    print(f"Saved source id: {source_id}")


def ask_source():
    return {
        "name": ask("Name", "RBC Trends Fintech"),
        "url": ask("URL", "https://trends.rbc.ru/trends/tag/fintech"),
        "source_type": ask("Source type", "site"),
        "is_active": confirm("Is active?", True),
        "parse_frequency_minutes": ask_int("Parse frequency minutes", 60),
    }


def ask_parser_config():
    defaults = DEFAULT_PARSER_CONFIG
    return {
        "max_age_days": ask_int("Max age days", defaults["max_age_days"]),
        "link_selector": ask("Link selector", defaults["link_selector"]),
        "date_selectors": ask_json("Date selectors JSON/null", defaults["date_selectors"]),
        "text_selector": ask_json("Text selector JSON/string", defaults["text_selector"]),
        "pause": ask_float("Pause", defaults["pause"]),
        "timeout": ask_int("Timeout", defaults["timeout"]),
        "user_agent": ask("User-Agent", defaults["user_agent"]),
        "use_fallback_date_search": confirm(
            "Use fallback date search?",
            defaults["use_fallback_date_search"],
        ),
        "date_formats": ask_json("Date formats JSON/null", defaults["date_formats"]),
    }


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value if value else default


def ask_int(prompt, default):
    return int(ask(prompt, str(default)))


def ask_float(prompt, default):
    return float(ask(prompt, str(default)))


def ask_json(prompt, default):
    value = ask(prompt, json.dumps(default, ensure_ascii=False))
    return parse_json_value(value)


def parse_json_value(value):
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def confirm(prompt, default=False):
    default_text = "y" if default else "n"
    answer = ask(f"{prompt} y/n", default_text)
    return parse_bool(answer)


def parse_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y", "да")


def test_source(url, config):
    parser = NewsParser(base_url=url, **config)
    return parser.parse()


def save_source(db_path, source, parser_config):
    init_db(db_path, seed_initial_source=False)
    with connect_db(db_path) as db:
        existing = db.execute("SELECT id FROM sources WHERE url = ?", (source["url"],)).fetchone()
        parser_config_json = json.dumps(parser_config, ensure_ascii=False)

        if existing:
            db.execute("""
                UPDATE sources
                SET
                    name = ?,
                    source_type = ?,
                    is_active = ?,
                    parse_frequency_minutes = ?,
                    parser_config = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                source["name"],
                source["source_type"],
                int(source["is_active"]),
                source["parse_frequency_minutes"],
                parser_config_json,
                existing["id"],
            ))
            source_id = existing["id"]
        else:
            cursor = db.execute("""
                INSERT INTO sources (
                    name,
                    url,
                    source_type,
                    is_active,
                    parse_frequency_minutes,
                    parser_config
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                source["name"],
                source["url"],
                source["source_type"],
                int(source["is_active"]),
                source["parse_frequency_minutes"],
                parser_config_json,
            ))
            source_id = cursor.lastrowid

        db.commit()
        return source_id


if __name__ == "__main__":
    main()
