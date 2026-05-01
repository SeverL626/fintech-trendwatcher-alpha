import hashlib
import io
import json
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin
from xml.etree import ElementTree

import dateparser
import requests
from bs4 import BeautifulSoup
from dateparser.search import search_dates

try:
    from back.init_db import DB_PATH, connect_db, init_db
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db, init_db


DEFAULT_PARSER_CONFIG = {
    "kind": "html",
    "max_age_days": 3,
    "link_selector": "a.g-inline-text-badges.js-item-link",
    "date_selectors": None,
    "text_selector": "article p",
    "pause": 0.5,
    "timeout": 15,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "verify_ssl": True,
    "use_fallback_date_search": True,
    "date_formats": None,
}


class NewsParser:
    def __init__(
        self,
        base_url,
        max_age_days=3,
        link_selector="a.g-inline-text-badges.js-item-link",
        date_selectors=None,
        text_selector="article p",
        pause=0.5,
        timeout=15,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        verify_ssl=True,
        use_fallback_date_search=True,
        date_formats=None,
        **_unused,
    ):
        self.base_url = base_url
        self.max_age_days = max_age_days
        self.link_selector = link_selector
        self.pause = pause
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}
        self.verify_ssl = verify_ssl
        self.use_fallback_date_search = use_fallback_date_search
        self.date_formats = date_formats
        self.text_selectors = [text_selector] if isinstance(text_selector, str) else text_selector
        self.date_selectors = date_selectors or [
            "meta[property='article:published_time']",
            "meta[name='pubdate']",
            "time[datetime]",
            ".article__date",
            ".post__date",
            ".date",
        ]
        self.age_limit = datetime.now() - timedelta(days=max_age_days)

    def parse(self):
        news = []
        soup = self._fetch_page(self.base_url)
        if not soup:
            return news

        links = soup.select(self.link_selector)
        for link_tag in links:
            href = link_tag.get("href")
            if not href:
                continue

            article_url = urljoin(self.base_url, href)
            title = link_tag.get_text(strip=True)
            time.sleep(self.pause)

            result = self._process_article(article_url, title)
            if result is False:
                continue
            if result:
                news.append(result)

        return news

    def _fetch_page(self, url):
        try:
            if not self.verify_ssl:
                disable_insecure_request_warning()
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except requests.RequestException:
            return None

    def _process_article(self, article_url, title):
        soup = self._fetch_page(article_url)
        if not soup:
            return None

        published_at = self._extract_date(soup)
        if not published_at:
            return None
        if published_at < self.age_limit:
            return False

        text = self._extract_text(soup)
        if not text:
            return None

        return {
            "url": article_url,
            "title": title,
            "published_at": published_at.strftime("%Y-%m-%d %H:%M:%S"),
            "text": text,
        }

    def _extract_date(self, soup):
        for selector in self.date_selectors:
            element = soup.select_one(selector)
            if not element:
                continue

            if element.name == "meta":
                value = element.get("content")
            elif element.name == "time":
                value = element.get("datetime")
            else:
                value = element.get_text(strip=True)

            parsed = parse_date(value, self.date_formats)
            if parsed:
                return parsed

        if self.use_fallback_date_search:
            result = search_dates(
                soup.get_text(" ", strip=True),
                languages=["ru", "en"],
                settings={"PREFER_DATES_FROM": "past"},
            )
            if result:
                return result[0][1].replace(tzinfo=None)

        return None

    def _extract_text(self, soup):
        elements = []
        for selector in self.text_selectors:
            elements.extend(soup.select(selector))
        if not elements:
            elements = soup.find_all("p")

        parts = []
        seen = set()
        for element in elements:
            if id(element) in seen:
                continue
            seen.add(id(element))
            text = element.get_text(strip=True)
            if text:
                parts.append(text)

        return "\n\n".join(parts)


def parse_date(value, date_formats=None):
    if not value:
        return None

    parsed = dateparser.parse(
        value,
        languages=["ru", "en"],
        settings={"PREFER_DATES_FROM": "past"},
        date_formats=date_formats,
    )
    return parsed.replace(tzinfo=None) if parsed else None


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


def run_parser_for_source_id(db_path=DB_PATH, source_id=None):
    if source_id is None:
        raise ValueError("source_id is required")

    init_db(db_path, seed_initial_source=False)
    with connect_db(db_path) as db:
        source = db.execute("""
            SELECT id, name, url, source_type, parser_config
            FROM sources
            WHERE id = ?
        """, (source_id,)).fetchone()

        if not source:
            return {
                "sources": 0,
                "created": 0,
                "duplicates": 0,
                "skipped": 0,
                "errors": 1,
                "empty_sources": 0,
                "summary": [f"Источник id={source_id} не найден"],
                "results": [],
                "error": "source_not_found",
            }

        try:
            result = parse_source(db, source)
        except Exception as error:
            result = source_error_result(source, error)

    return aggregate_parser_results([result])


def parse_source(db, source):
    config = load_parser_config(source["parser_config"])
    kind = config.get("kind") or source["source_type"] or "html"
    items = parse_items(source["url"], source["name"], kind, config)

    created = 0
    duplicates = 0
    for item in items:
        if insert_raw_news(db, source["id"], item):
            created += 1
        else:
            duplicates += 1

    db.execute("UPDATE sources SET last_parsed_at = CURRENT_TIMESTAMP WHERE id = ?", (source["id"],))
    db.commit()

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "source_type": source["source_type"],
        "kind": kind,
        "found": len(items),
        "created": created,
        "duplicates": duplicates,
        "skipped": duplicates,
        "errors": 0,
        "empty": len(items) == 0,
    }


def aggregate_parser_results(results):
    errors = sum(1 for item in results if item.get("error"))
    empty_sources = sum(
        1
        for item in results
        if not item.get("error") and item.get("found", 0) == 0
    )
    duplicates = sum(item.get("duplicates", item.get("skipped", 0)) for item in results)
    return {
        "sources": len(results),
        "created": sum(item["created"] for item in results),
        "duplicates": duplicates,
        "skipped": duplicates,
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
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "source_url": source["url"],
        "source_type": source["source_type"],
        "kind": config.get("kind") or source["source_type"] or "html",
        "found": 0,
        "created": 0,
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
        return (
            f"{result.get('source_name')} ({result.get('source_url')}): "
            "ничего не найдено"
        )
    return (
        f"{result.get('source_name')} ({result.get('source_url')}): "
        f"найдено {result.get('found', 0)}, "
        f"сохранено {result.get('created', 0)}, "
        f"дублей {result.get('duplicates', result.get('skipped', 0))}"
    )


def parse_items(url, source_name, kind, config):
    normalized_kind = kind.lower()
    if normalized_kind in ("rss", "xml", "xml_api"):
        return parse_xml_feed(url, source_name, config)
    if normalized_kind in ("json", "json_api", "rest_api"):
        return parse_json_endpoint(url, source_name, config)
    if normalized_kind == "html_files":
        return parse_html_files(url, source_name, config)
    if normalized_kind == "yandex_search":
        return parse_yandex_search(url, source_name, config)

    parser = NewsParser(base_url=url, **config)
    return parser.parse()


def parse_xml_feed(url, source_name, config):
    response = fetch_response(url, config)
    root = ElementTree.fromstring(response.content)
    items = []

    if local_name(root.tag) in ("rss", "rdf", "feed"):
        for element in root.iter():
            if local_name(element.tag) != "item":
                continue
            item = xml_feed_item_to_news(url, source_name, config, element)
            if item:
                items.append(item)
        for element in root.iter():
            if local_name(element.tag) != "entry":
                continue
            item = atom_item_to_news(url, source_name, config, element)
            if item:
                items.append(item)
        return items

    item_tags = set(config.get("item_tags") or ["Item", "News", "Record"])
    for element in root.iter():
        if local_name(element.tag) not in item_tags:
            continue
        item = generic_xml_item_to_news(url, source_name, config, element)
        if item:
            items.append(item)

    return items


def xml_feed_item_to_news(base_url, source_name, config, element):
    title = child_text(element, ["title"]) or source_name
    article_url = child_text(element, ["link", "guid"]) or base_url
    published_at = normalize_published_at(child_text(element, ["pubDate", "dc:date", "date"]))
    if not is_recent(published_at, config.get("max_age_days")):
        return None

    text = html_to_text(
        child_text(element, ["description", "content:encoded", "summary"])
        or title
    )
    return make_news_item(article_url, title, published_at, text, {
        "adapter": "rss",
        "source": source_name,
    })


def atom_item_to_news(base_url, source_name, config, element):
    title = child_text(element, ["title"]) or source_name
    link = base_url
    for child in element:
        if local_name(child.tag) == "link" and child.get("href"):
            link = child.get("href")
            break
    published_at = normalize_published_at(child_text(element, ["published", "updated"]))
    if not is_recent(published_at, config.get("max_age_days")):
        return None

    text = html_to_text(child_text(element, ["summary", "content"]) or title)
    return make_news_item(link, title, published_at, text, {
        "adapter": "atom",
        "source": source_name,
    })


def generic_xml_item_to_news(base_url, source_name, config, element):
    title = child_text(element, config.get("title_fields") or ["Title", "title", "Name", "name"]) or source_name
    article_url = child_text(element, config.get("url_fields") or ["Url", "URL", "Link", "link"]) or base_url
    article_url = urljoin(config.get("url_prefix") or base_url, article_url)
    published_at = normalize_published_at(child_text(element, config.get("date_fields") or ["Date", "date"]))
    if not is_recent(published_at, config.get("max_age_days")):
        return None

    text = html_to_text(child_text(element, config.get("text_fields") or ["Text", "Description", "text"]) or title)
    return make_news_item(article_url, title, published_at, text, {
        "adapter": "xml",
        "source": source_name,
        "xml_tag": local_name(element.tag),
    })


def parse_json_endpoint(url, source_name, config):
    response = fetch_response(url, config)
    payload = response.json()
    records = extract_json_records(payload)
    items = []
    max_items = int(config.get("max_items") or 50)

    for index, record in enumerate(records[:max_items], start=1):
        title = (
            value_from_keys(record, ["title", "name", "shortname", "SECNAME", "BOARDNAME"])
            or f"{source_name}: запись {index}"
        )
        published_at = normalize_published_at(
            value_from_keys(record, ["published_at", "date", "TRADEDATE", "updated_at"])
        )
        if not is_recent(published_at, config.get("max_age_days")):
            continue

        text = json.dumps(record, ensure_ascii=False, indent=2)
        row_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        items.append(make_news_item(f"{url}#{row_hash}", title, published_at, text, {
            "adapter": "json",
            "source": source_name,
            "record": record,
        }))

    return items


def parse_html_files(url, source_name, config):
    response = fetch_response(url, config)
    soup = BeautifulSoup(response.text, "lxml")
    link_selector = config.get("link_selector") or "a[href]"
    file_extensions = tuple(config.get("file_extensions") or [".pdf", ".xls", ".xlsx", ".csv", ".zip"])
    url_contains = config.get("url_contains") or []
    max_items = int(config.get("max_items") or 50)
    items = []
    seen_urls = set()

    for link in soup.select(link_selector):
        href = link.get("href")
        if not href:
            continue

        file_url = urljoin(url, href)
        lowered = file_url.lower().split("?", 1)[0]
        is_file = lowered.endswith(file_extensions)
        is_interesting_page = any(marker in file_url for marker in url_contains)
        if not is_file and not is_interesting_page:
            continue
        if file_url in seen_urls:
            continue

        seen_urls.add(file_url)
        title = link.get_text(" ", strip=True) or file_url.rsplit("/", 1)[-1] or source_name
        items.append(parse_file_or_link(file_url, title, source_name, config))
        if len(items) >= max_items:
            break

    return items


def parse_file_or_link(url, title, source_name, config):
    lowered = url.lower().split("?", 1)[0]
    if lowered.endswith(".pdf"):
        return parse_pdf_link(url, title, source_name, config)
    if lowered.endswith((".xls", ".xlsx", ".csv")):
        return parse_table_link(url, title, source_name, config)

    return make_news_item(url, title, None, f"Найдена ссылка источника: {url}", {
        "adapter": "html_files",
        "source": source_name,
        "asset_url": url,
    })


def parse_pdf_link(url, title, source_name, config):
    try:
        response = fetch_response(url, config)
        text = extract_pdf_text(response.content)
        raw_data = {
            "adapter": "pdf",
            "source": source_name,
            "content_type": response.headers.get("content-type"),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        }
    except Exception as error:
        text = f"Найден PDF-файл: {url}\nИзвлечь текст не удалось: {error}"
        raw_data = {
            "adapter": "pdf",
            "source": source_name,
            "asset_url": url,
            "error": str(error),
        }

    return make_news_item(url, title, None, text or f"Найден PDF-файл: {url}", raw_data)


def parse_table_link(url, title, source_name, config):
    try:
        response = fetch_response(url, config)
        summary = extract_table_summary(response.content, url)
        raw_data = {
            "adapter": "table",
            "source": source_name,
            "content_type": response.headers.get("content-type"),
            "sha256": hashlib.sha256(response.content).hexdigest(),
            "summary": summary,
        }
        text = json.dumps(summary, ensure_ascii=False, indent=2)
    except Exception as error:
        text = f"Найден табличный файл: {url}\nИзвлечь таблицу не удалось: {error}"
        raw_data = {
            "adapter": "table",
            "source": source_name,
            "asset_url": url,
            "error": str(error),
        }

    return make_news_item(url, title, None, text, raw_data)


def parse_yandex_search(url, source_name, config):
    import os

    missing = [
        env_name
        for env_name in config.get("requires_env", [])
        if not os.getenv(env_name)
    ]
    if missing:
        raise ValueError(f"missing environment variables: {', '.join(missing)}")

    response = requests.post(
        url,
        headers={
            "Authorization": f"Api-Key {os.getenv('YANDEX_API_KEY')}",
            "Content-Type": "application/json",
        },
        json={
            "query": {
                "searchType": "SEARCH_TYPE_RU",
                "queryText": config.get("query_text"),
                "page": "0",
            },
            "sortSpec": {
                "sortMode": "SORT_MODE_BY_TIME",
                "sortOrder": "SORT_ORDER_DESC",
            },
            "groupSpec": {
                "groupMode": "GROUP_MODE_FLAT",
                "groupsOnPage": "20",
                "docsInGroup": "1",
            },
            "responseFormat": "FORMAT_XML",
            "period": "PERIOD_DAY",
            "l10n": "LOCALIZATION_RU",
            "folderId": os.getenv("YANDEX_FOLDER_ID"),
        },
        timeout=config.get("timeout") or 30,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    items = []
    for index, doc in enumerate(root.iter(), start=1):
        if local_name(doc.tag) != "doc":
            continue
        title = child_text(doc, ["title"]) or f"{source_name}: результат {index}"
        doc_url = child_text(doc, ["url"]) or url
        text = html_to_text(child_text(doc, ["headline", "passages"]) or title)
        items.append(make_news_item(doc_url, title, None, text, {
            "adapter": "yandex_search",
            "source": source_name,
        }))
    return items


def fetch_response(url, config):
    headers = {"User-Agent": config.get("user_agent") or DEFAULT_PARSER_CONFIG["user_agent"]}
    verify_ssl = config.get("verify_ssl", True)
    if not verify_ssl:
        disable_insecure_request_warning()
    response = requests.get(
        url,
        headers=headers,
        timeout=config.get("timeout") or 15,
        verify=verify_ssl,
    )
    response.raise_for_status()
    return response


def disable_insecure_request_warning():
    try:
        from urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    except Exception:
        pass


def make_news_item(url, title, published_at, text, raw_data):
    return {
        "url": url,
        "title": title,
        "published_at": published_at,
        "text": text or title or url,
        "raw_data": raw_data,
    }


def html_to_text(value):
    if not value:
        return ""
    return BeautifulSoup(str(value), "lxml").get_text(" ", strip=True)


def normalize_published_at(value):
    parsed = parse_date(str(value)) if value else None
    return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else None


def is_recent(published_at, max_age_days):
    if not published_at:
        return True
    parsed = parse_date(published_at)
    if not parsed:
        return True
    return parsed >= datetime.now() - timedelta(days=int(max_age_days or 3))


def local_name(tag):
    return str(tag).rsplit("}", 1)[-1].split(":", 1)[-1]


def child_text(element, names):
    normalized_names = {local_name(name).lower() for name in names}
    for child in element.iter():
        if child is element:
            continue
        if local_name(child.tag).lower() in normalized_names:
            text = child.text or child.get("href") or child.get("content")
            if text:
                return text.strip()
    return None


def value_from_keys(record, keys):
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        value = record.get(key)
        if value is None:
            value = lowered.get(str(key).lower())
        if value not in (None, ""):
            return value
    return None


def extract_json_records(payload):
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    moex_records = extract_moex_records(payload)
    if moex_records:
        return moex_records

    for key in ("items", "news", "results", "documents", "data", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_json_records(value)
            if nested:
                return nested

    records = []
    for value in payload.values():
        if isinstance(value, dict):
            records.extend(extract_json_records(value))
        elif isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def extract_moex_records(payload):
    records = []
    for table_name, table in payload.items():
        if not isinstance(table, dict):
            continue
        columns = table.get("columns")
        rows = table.get("data")
        if not isinstance(columns, list) or not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, list):
                record = dict(zip(columns, row))
                record["_table"] = table_name
                records.append(record)
    return records


def extract_pdf_text(body):
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError("для извлечения PDF установите pypdf") from error

    reader = PdfReader(io.BytesIO(body))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages).strip()


def extract_table_summary(body, url):
    try:
        import pandas as pd
    except ImportError as error:
        raise RuntimeError("для извлечения таблиц установите pandas и openpyxl") from error

    bio = io.BytesIO(body)
    lowered = url.lower().split("?", 1)[0]
    if lowered.endswith(".csv"):
        frame = pd.read_csv(bio)
    else:
        frame = pd.read_excel(bio)

    return {
        "rows": int(len(frame)),
        "columns": list(map(str, frame.columns)),
        "preview": frame.head(5).fillna("").to_dict(orient="records"),
    }


def load_parser_config(raw_config):
    config = dict(DEFAULT_PARSER_CONFIG)
    if raw_config:
        loaded_config = json.loads(raw_config)
        if not isinstance(loaded_config, dict):
            raise ValueError("parser_config must be a JSON object")
        config.update(loaded_config)
    return config


def insert_raw_news(db, source_id, item):
    cursor = db.execute("""
        INSERT OR IGNORE INTO raw_news (
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
    return cursor.rowcount == 1


def make_content_hash(title, text):
    value = f"{title or ''}\n{text or ''}".strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps(run_parser_from_db(), ensure_ascii=False, indent=2))
