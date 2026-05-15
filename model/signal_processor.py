import json
import os
import re
import time

import requests

try:
    from back.init_db import DB_PATH, connect_db
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db


OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it")
OPENROUTER_TIMEOUT_SECONDS = 60
OPENROUTER_MAX_RETRIES = 3
OPENROUTER_RETRY_SECONDS = 20
OPENROUTER_REQUEST_DELAY_SECONDS = 0
MAX_MODEL_REQUESTS_PER_RUN = None
MAX_INPUT_TEXT_CHARS = 14000
DEFAULT_SIGNAL_CATEGORIES = (
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


class OpenRouterRateLimitError(RuntimeError):
    pass


class OpenRouterRequestError(RuntimeError):
    pass


def process_new_raw_news(db_path=DB_PATH, limit=None):
    get_openrouter_api_key()
    limit = normalize_limit(
        limit,
        default=None,
        maximum=None,
    )
    results = []

    with connect_db(db_path) as db:
        categories = load_signal_categories(db)
        query = """
            SELECT
                rn.id,
                rn.source_id,
                rn.url,
                rn.title,
                rn.text,
                rn.published_at,
                rn.parsed_at,
                rn.raw_data,
                s.name AS source_name,
                s.source_type
            FROM raw_news rn
            JOIN sources s ON s.id = rn.source_id
            WHERE rn.status = 'new'
            ORDER BY datetime(COALESCE(rn.published_at, rn.parsed_at)) ASC, rn.id ASC
        """
        params = ()
        if limit is not None:
            query += "\n            LIMIT ?"
            params = (limit,)
        rows = db.execute(query, params).fetchall()

        for row in rows:
            result = process_raw_news_row(db, row, categories)
            results.append(result)
            if result.get("status") == "rate_limited":
                break

    openrouter_usage = summarize_openrouter_usage(results)

    return {
        "mode": "single_model",
        "requested_limit": limit or "all",
        "max_requests_per_run": "all",
        "model": OPENROUTER_MODEL,
        "processed_items": len(results),
        "signals_created": sum(item.get("signals_created", 0) for item in results),
        "errors": sum(1 for item in results if item.get("status") == "error"),
        "rate_limited": any(item.get("status") == "rate_limited" for item in results),
        "openrouter": openrouter_usage,
        "results": results,
    }


def process_raw_news_row(db, row, categories):
    raw_news_id = row["id"]
    if signal_exists_for_raw_news(db, raw_news_id):
        mark_raw_news_status(db, raw_news_id, "processed")
        return {
            "raw_news_id": raw_news_id,
            "status": "already_processed",
            "signals_created": 0,
        }

    mark_raw_news_status(db, raw_news_id, "processing")

    try:
        card, usage = build_signal_card_with_openrouter(row, categories, OPENROUTER_MODEL)
        normalized_card = normalize_signal_card(card, row, categories, OPENROUTER_MODEL)
        signal_id = insert_signal(db, row, normalized_card)
        usage_cost = get_usage_cost(usage)
        card_summary = {
            "model": normalized_card["model"],
            "signal_id": signal_id,
            "headline": normalized_card["headline"],
            "category": normalized_card["category"],
            "hotness": normalized_card["hotness"],
            "usage": usage,
            "cost": usage_cost,
        }
        sleep_between_requests()

        mark_raw_news_status(db, raw_news_id, "processed")
        return {
            "raw_news_id": raw_news_id,
            "signal_ids": [signal_id],
            "status": "processed",
            "signals_created": 1,
            "cost": usage_cost,
            "cards": [card_summary],
        }
    except Exception as error:
        message = sanitize_error_message(error)
        if isinstance(error, OpenRouterRateLimitError):
            mark_raw_news_status(db, raw_news_id, "error", message)
            return {
                "raw_news_id": raw_news_id,
                "status": "rate_limited",
                "error": message,
            }
        mark_raw_news_status(db, raw_news_id, "error", message)
        return {
            "raw_news_id": raw_news_id,
            "status": "error",
            "error": message,
        }


def signal_exists_for_raw_news(db, raw_news_id):
    raw_news_id = int(raw_news_id)
    rows = db.execute("""
        SELECT sources
        FROM signals
        WHERE sources LIKE ?
    """, (f"%{raw_news_id}%",)).fetchall()

    for row in rows:
        sources = normalize_sources_value(row["sources"])
        if isinstance(sources, int) and sources == raw_news_id:
            return True
        if isinstance(sources, list) and raw_news_id in sources:
            return True
    return False


def build_signal_card_with_openrouter(row, categories, model):
    api_key = get_openrouter_api_key()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": build_signal_prompt(row, categories),
            },
        ],
        "temperature": 0.2,
        "max_tokens": 700,
        "response_format": {"type": "json_object"},
    }
    response = post_openrouter_with_retries(api_key, payload)
    handle_openrouter_http_error(response)
    payload = response.json()
    response_text = extract_openrouter_text(payload)
    return parse_json_response(response_text), normalize_openrouter_usage(payload.get("usage"))


def post_openrouter_with_retries(api_key, payload):
    last_response = None

    for attempt in range(OPENROUTER_MAX_RETRIES + 1):
        response = requests.post(
            OPENROUTER_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://127.0.0.1:5000"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "Fintech Trendwatcher"),
            },
            json=payload,
            timeout=OPENROUTER_TIMEOUT_SECONDS,
        )
        if response.status_code != 429:
            return response

        last_response = response
        if attempt >= OPENROUTER_MAX_RETRIES:
            break

        retry_after = parse_retry_after(response)
        sleep_seconds = retry_after or OPENROUTER_RETRY_SECONDS * (attempt + 1)
        time.sleep(sleep_seconds)

    raise OpenRouterRateLimitError(format_openrouter_error(last_response))


def handle_openrouter_http_error(response):
    if response.status_code == 429:
        raise OpenRouterRateLimitError(format_openrouter_error(response))
    if response.status_code >= 400:
        raise OpenRouterRequestError(format_openrouter_error(response))


def get_openrouter_api_key():
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return api_key


def format_openrouter_error(response):
    if response is None:
        return "OpenRouter request failed"
    body = response.text[:1000] if response.text else ""
    return f"OpenRouter API HTTP {response.status_code}: {body}".strip()


def normalize_openrouter_usage(usage):
    if not isinstance(usage, dict):
        return {}

    normalized = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cost",
        "cost_details",
        "prompt_tokens_details",
        "completion_tokens_details",
    ):
        if key in usage:
            normalized[key] = usage[key]
    return normalized


def summarize_openrouter_usage(results):
    run_cost = sum(get_usage_cost(item.get("usage", {})) for item in iter_result_cards(results))
    if not run_cost:
        run_cost = sum(get_usage_cost(item) for item in results)
    return {
        "model": OPENROUTER_MODEL,
        "requests_limit": "all",
        "requests_sent": count_openrouter_requests(results),
        "run_cost": round(run_cost, 8) if run_cost is not None else None,
    }


def count_openrouter_requests(results):
    return sum(1 for item in results if item.get("status") in {"processed", "error", "rate_limited"})


def iter_result_cards(results):
    for item in results:
        cards = item.get("cards") or []
        for card in cards:
            yield card


def get_usage_cost(usage):
    if not isinstance(usage, dict):
        return 0.0
    return coerce_float(usage.get("cost")) or coerce_float(usage.get("cost_usd")) or 0.0


def coerce_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_retry_after(response):
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0, min(300, int(value)))
    except ValueError:
        return None


def sleep_between_requests():
    if OPENROUTER_REQUEST_DELAY_SECONDS > 0:
        time.sleep(min(300, OPENROUTER_REQUEST_DELAY_SECONDS))


def build_signal_prompt(row, categories):
    title = clean_text(row["title"]) or "нет"
    text = trim_for_model(clean_text(row["text"]))
    published_at = row["published_at"] or row["parsed_at"] or "не указано"
    source_name = clean_text(row["source_name"]) or "не указан"
    url = clean_text(row["url"]) or "не указан"
    category_list = "\n".join(f"- {category}" for category in categories)
    category_guide = build_category_guide(categories)

    return f"""
Ты — аналитик трендвотчера для Альфа-Банка. Оцени одну публикацию и верни только один валидный JSON-объект: без markdown, пояснений, текста до/после JSON и trailing comma. Факты не выдумывай; если текст не на русском, передай смысл на русском.

Фокус: российский банковский и финтех-рынок. Для Альфа-Банка важнее РФ, ЦБ РФ, НСПК, СБП, крупные российские банки, платежная инфраструктура, клиентские сценарии, риск, комплаенс, антифрод, идентификация и новые банковские/финтех-системы. Глобальные события важны только при понятном канале влияния на российский банк.

Очисти навигацию, рекламу, меню, boilerplate и повторы заголовка. Если содержательной новости нет — hotness=1.

Шкала hotness:
1 — шум: нерелевантно финансам/банкам/финтеху; общий PR; кадровые новости; конференции; абстрактные советы; навигация/boilerplate; риски без новой схемы, цифр, масштаба или банковского вывода. Для 1: why_now="--", summary="", draft="".
2 — фон: обычные отчеты, таблицы, статистика, финансовая отчетность без неожиданного вывода, локальные новости, зарубежный финтех без прямого влияния на РФ, глобальный фон без прямого действия для банка.
3 — средние новости: есть конкретное событие и связь с продуктами, платежами, клиентским опытом, рисками, конкурентами, регулированием или рынком; исследования с косвенным влиянием; масштаб/срочность умеренные.
4 — важные, но не срочные: российский регулятор, крупный банк, финтех, НСПК/СБП/ЦБ РФ или инфраструктурный игрок меняет правила, продукт, комиссии, UX, риск, комплаенс или конкурентную позицию; исследования с прямым влиянием, но без срочной реакции. Глобальное событие ставь 4 только при явном канале влияния на российские банки: санкции, платежи, валютные ограничения, трансграничные расчеты, ликвидность, ставки/курсы с прямым рыночным эффектом.
5 — важные и срочные: обязательное требование ЦБ РФ или закона с дедлайном; крупное изменение СБП/НСПК/цифрового рубля/open banking/биометрии/идентификации; массовая атака на клиентов банков; продолжающийся массовый сбой критической банковской/платежной инфраструктуры; резкое изменение правил; крупное действие системного российского конкурента; санкции/ограничения, прямо затрагивающие российские банки; очень важные исследования с прямым практическим выводом. Нужна реакция за 24-72 часа.

Правила оценки:
- Если сомневаешься между двумя оценками, выбери меньшую.
- Не ставь 3+ без конкретного события, масштаба, источника влияния или понятного вывода для банка.
- Отчетность сама по себе обычно 2; выше только при неожиданном результате или прямом конкурентном выводе.
- Сухой файл Росстата, XLS/XLSX/CSV-таблица или набор данных без новости, решения, риска или продуктового вывода: hotness=2, why_now="Фоновая статистика без прямого действия для банка.", summary="Вышел отчёт." или "Вышла таблица.".
- Для обычных новостей, пресс-релизов, заявлений, запусков, регуляторики, аналитики и СМИ не используй why_now="Отчёт"; пиши банковский смысл события.
- Глобальная макроэкономика без прямого канала влияния на российские банки обычно 1-2. Глобальные ставки, ФРС/ЕЦБ и зарубежные регуляторы обычно 2-3; ставь 4 только при явном влиянии на РФ, банки, платежи, санкции, ликвидность или рынки.
- Иностранные финтех-запуски, платежные продукты, embedded finance, BNPL, процессинг, identity/fraud-tech обычно 2, а не 1, если есть конкретный продукт, сделка, запуск или изменение клиентского сценария. Если связи с банками/финтехом нет или это общий PR без банковского вывода — 1.
- Регуляторное обсуждение без сроков обычно 3; проект/обсуждение ЦБ РФ без дедлайна — 3; решение ЦБ РФ — 4; обязательное изменение ЦБ РФ/закона с дедлайном — 5.
- Новые российские финтех- и банковские системы: 5 только при обязательности, дедлайне, массовом внедрении или влиянии на инфраструктуру, иначе 3-4.
- Сбой критической банковской/платежной инфраструктуры: 4 только если он массовый, продолжается, влияет на клиентов/платежи прямо сейчас или требует реакции банка в 24-72 часа; если локализован или описан постфактум — 3 или 4.
- Кибер/мошенничество: общие советы 1; новая схема с цифрами/масштабом 3; массовая атака на клиентов банков 4-5.

Категории: выбери ровно одну из списка, новые не придумывай; если подходят несколько, выбери главную по банковскому сигналу.
{category_list}

Ориентир по категориям:
{category_guide}

why_now: не пересказ, а банковский смысл сейчас: риск, продуктовый эффект, изменение правил, конкурентное давление, влияние на платежи, клиентов, антифрод или комплаенс. Не начинай с "Вышел", "Сообщили", "Объявили", "Опубликован", "Компания сообщила", "ЦБ сообщил". Для регуляторики укажи действие/риск/срок/изменение процесса; для конкурентов — влияние на конкуренцию, продукт или клиентский сценарий; для платежей/финтеха — сценарий, лимит, UX, комиссию или инфраструктуру; для мошенничества/кибера — риск для клиентов или банка; для зарубежных новостей — канал влияния на РФ/банк, иначе hotness 1-2.
Хорошие примеры why_now: "Банкам может потребоваться обновить комплаенс-процессы под новые требования ЦБ."; "Изменение лимитов может повлиять на платежные сценарии малого бизнеса."; "Конкурент усиливает клиентский сценарий и может забрать часть транзакций."; "Возможны новые ограничения для расчетов и операций российских банков."; "Фоновая статистика без прямого действия для банка."

Формат JSON:
{{
  "headline": "нейтральный заголовок 5-10 слов",
  "hotness": 1,
  "why_now": "банковский смысл события сейчас, не пересказ новости",
  "category": "одна из допустимых категорий",
  "summary": "для hotness=1 пусто; иначе 1-3 коротких предложения с фактами",
  "draft": "пусто, если нет ошибки, сомнения или ограничения качества"
}}

Входные данные:
Дата публикации: {published_at}
Источник: {source_name}
URL: {url}
Заголовок: {title}
Текст:
{text}
""".strip()


def build_category_guide(categories):
    descriptions = {
        "Регулирование и комплаенс": "ЦБ РФ, законы, требования, лицензии, AML/KYC, Росфинмониторинг, проверки, ограничения для банков и МФО.",
        "Платежи и инфраструктура": "СБП, НСПК, карты, переводы, эквайринг, процессинг, платежные системы, сбои платежей, лимиты переводов.",
        "Антифрод и кибербезопасность": "мошеннические схемы, утечки данных, кибератаки, защита клиентов, антифрод-сервисы.",
        "Банковские продукты и клиентский опыт": "кредиты, вклады, карты, подписки, мобильные приложения, UX, новые клиентские сервисы банков.",
        "Конкуренты и банковский рынок": "действия российских банков и финтех-конкурентов, которые могут повлиять на клиентов, продукты, комиссии или долю рынка.",
        "Финтех и новые технологии": "BNPL, embedded finance, open banking, AI в банках, цифровые сервисы, neobank, новые финтех-модели.",
        "Идентификация и биометрия": "ЕБС, биометрия, цифровой ID, удалённая идентификация, KYC, identity-tech.",
        "Санкции и ограничения": "санкции, валютные ограничения, ограничения на расчеты, трансграничные платежи, международные запреты для банков.",
        "Макроэкономика и ставки": "ключевая ставка, инфляция, ВВП, курс, ДКП, прогнозы ЦБ/Минэка, макрофон.",
        "Рынки и инвестиции": "фондовый рынок, облигации, акции, IPO, брокеры, инвестиционные продукты, Мосбиржа.",
        "Финансовые результаты и отчетность": "прибыль, выручка, дивиденды, квартальная/годовая отчетность банков и компаний.",
        "Статистика и данные": "Росстат, таблицы, XLS/CSV, статистические наборы данных и сухие отчёты без прямого банковского вывода.",
    }
    return "\n".join(
        f"- {category}: {descriptions.get(category, 'выбери, если это наиболее близкая категория')}"
        for category in categories
    )


def extract_openrouter_text(payload):
    try:
        text = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"Unexpected OpenRouter response: {payload}") from error
    if not text or not text.strip():
        raise RuntimeError(f"OpenRouter returned empty text: {payload}")
    return text


def parse_json_response(value):
    text = str(value or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"OpenRouter returned invalid JSON: {text[:1000]}") from error
    if not isinstance(parsed, dict):
        raise RuntimeError("OpenRouter JSON response must be an object")
    return parsed


def normalize_signal_card(card, row, categories, model):
    headline = clean_text(card.get("headline")) or clean_text(row["title"]) or "Без заголовка"
    summary = clean_text(card.get("summary")) or headline
    draft = clean_text(card.get("draft"))
    why_now = clean_text(card.get("why_now")) or "Недостаточно данных для оценки срочности."
    category = clean_text(card.get("category"))
    if category not in categories:
        category = categories[0]
    hotness = normalize_hotness(card.get("hotness"))
    if why_now == "--":
        hotness = 1
    if is_plain_report_row(row):
        hotness = max(hotness, 2)
        if hotness <= 2:
            hotness = 2
            why_now = "Фоновая статистика без прямого действия для банка."
            summary = get_plain_report_summary(row)
            draft = ""
    if hotness == 1:
        summary = ""

    return {
        "headline": headline[:300],
        "hotness": hotness,
        "why_now": why_now,
        "category": category,
        "summary": summary,
        "draft": draft,
        "model": model,
    }


def is_plain_report_row(row):
    source_name = clean_text(row["source_name"]).casefold()
    url = clean_text(row["url"]).casefold()
    raw_data = parse_raw_data(row["raw_data"])

    adapter = clean_text(raw_data.get("adapter")).casefold() if isinstance(raw_data, dict) else ""
    file_extension = clean_text(raw_data.get("file_extension")).casefold() if isinstance(raw_data, dict) else ""

    return (
        adapter == "rosstat"
        or "росстат" in source_name
        or file_extension in {".xls", ".xlsx", ".csv"}
        or any(url.endswith(extension) for extension in (".xls", ".xlsx", ".csv"))
    )


def get_plain_report_summary(row):
    url = clean_text(row["url"]).lower()
    title = clean_text(row["title"]).casefold()
    if any(extension in url for extension in (".xls", ".xlsx", ".csv")) or "таблиц" in title:
        return "Вышла таблица."
    return "Вышел отчёт."


def parse_raw_data(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def insert_signal(db, row, card):
    cursor = db.execute("""
        INSERT INTO signals (
            headline,
            hotness,
            why_now,
            category,
            sources,
            summary,
            draft
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        card["headline"],
        card["hotness"],
        card["why_now"],
        card["category"],
        row["id"],
        card["summary"],
        card["draft"],
    ))
    db.commit()
    return cursor.lastrowid


def mark_raw_news_status(db, raw_news_id, status, error_message=None):
    db.execute("""
        UPDATE raw_news
        SET status = ?,
            error_message = ?
        WHERE id = ?
    """, (status, error_message, raw_news_id))
    db.commit()


def list_signals(db_path=DB_PATH, limit=20):
    limit = normalize_limit(limit, default=20, maximum=100)
    with connect_db(db_path) as db:
        rows = db.execute("""
            SELECT id, headline, hotness, why_now, category, sources, summary, draft
            FROM signals
            WHERE draft IS NULL OR draft NOT LIKE 'DUBLICATE OF %'
            ORDER BY id DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [row_to_signal_dict(row) for row in rows]


def row_to_signal_dict(row):
    result = dict(row)
    result["sources"] = normalize_sources_value(result.get("sources"))
    result["draft"] = normalize_public_draft(result.get("draft"))
    return result


def normalize_public_draft(value):
    if not value:
        return value
    try:
        draft_data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value
    if not isinstance(draft_data, dict) or "embedding" not in draft_data:
        return value
    return draft_data.get("previous_draft") or ""


def normalize_sources_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip()
    if re.fullmatch(r"\d+", text):
        return int(text)
    if "," in text and not text.startswith("["):
        return [int(part) for part in re.findall(r"\d+", text)]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def load_signal_categories(db):
    schema_row = db.execute("""
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = 'signals'
    """).fetchone()
    schema_sql = schema_row["sql"] if schema_row else ""
    match = re.search(r"category\s+TEXT\s+NOT\s+NULL\s+CHECK\s*\(\s*category\s+IN\s*\((?P<body>.*?)\)\s*\)", schema_sql, re.S)
    if not match:
        return list(DEFAULT_SIGNAL_CATEGORIES)
    categories = re.findall(r"'([^']+)'", match.group("body"))
    return categories or list(DEFAULT_SIGNAL_CATEGORIES)


def normalize_hotness(value):
    match = re.search(r"\d+", str(value or ""))
    if not match:
        number = 1
    else:
        number = int(match.group(0))
    return min(5, max(1, number))


def normalize_limit(value, default=10, maximum=50):
    if value is None or str(value).strip() == "":
        return default
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default
    if limit is None:
        return None
    if maximum is None:
        return max(1, limit)
    return min(maximum, max(1, limit))


def ensure_model_configured():
    if not os.getenv("OPENROUTER_API_KEY"):
        raise RuntimeError("OPENROUTER_API_KEY is not set")


def clean_text(value):
    text = str(value or "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def trim_for_model(value):
    text = str(value or "")
    if len(text) <= MAX_INPUT_TEXT_CHARS:
        return text
    return text[:MAX_INPUT_TEXT_CHARS].rsplit(" ", 1)[0] + "\n[Текст обрезан по длине]"


def sanitize_error_message(error):
    message = str(error)
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", message)
    return message[:1000]


if __name__ == "__main__":
    print(json.dumps(process_new_raw_news(), ensure_ascii=False, indent=2))
