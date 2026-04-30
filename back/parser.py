import hashlib
import json
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin

import dateparser
import requests
from bs4 import BeautifulSoup
from dateparser.search import search_dates

try:
    from back.init_db import DB_PATH, connect_db, init_db
except ModuleNotFoundError:
    from init_db import DB_PATH, connect_db, init_db


DEFAULT_PARSER_CONFIG = {
    "max_age_days": 2,
    "link_selector": "a.g-inline-text-badges.js-item-link",
    "date_selectors": None,
    "text_selector": "article p",
    "pause": 0.5,
    "timeout": 15,
    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "use_fallback_date_search": True,
    "date_formats": None,
}


class NewsParser:
    def __init__(
        self,
        base_url,
        max_age_days=2,
        link_selector="a.g-inline-text-badges.js-item-link",
        date_selectors=None,
        text_selector="article p",
        pause=0.5,
        timeout=15,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        use_fallback_date_search=True,
        date_formats=None,
    ):
        self.base_url = base_url
        self.max_age_days = max_age_days
        self.link_selector = link_selector
        self.pause = pause
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}
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
            response = requests.get(url, headers=self.headers, timeout=self.timeout)
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
    init_db(db_path)
    results = []

    with connect_db(db_path) as db:
        sources = db.execute("""
            SELECT id, name, url, parser_config
            FROM sources
            WHERE is_active = 1
            ORDER BY id ASC
        """).fetchall()

        for source in sources:
            try:
                result = parse_source(db, source)
            except Exception as error:
                result = {
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "found": 0,
                    "created": 0,
                    "skipped": 0,
                    "error": str(error),
                }
            results.append(result)

    return {
        "sources": len(results),
        "created": sum(item["created"] for item in results),
        "skipped": sum(item["skipped"] for item in results),
        "results": results,
    }


def parse_source(db, source):
    config = load_parser_config(source["parser_config"])
    parser = NewsParser(base_url=source["url"], **config)
    items = parser.parse()

    created = 0
    skipped = 0
    for item in items:
        if insert_raw_news(db, source["id"], item):
            created += 1
        else:
            skipped += 1

    db.execute("UPDATE sources SET last_parsed_at = CURRENT_TIMESTAMP WHERE id = ?", (source["id"],))
    db.commit()

    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "found": len(items),
        "created": created,
        "skipped": skipped,
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
        json.dumps(item, ensure_ascii=False),
        "new",
    ))
    return cursor.rowcount == 1


def make_content_hash(title, text):
    value = f"{title or ''}\n{text or ''}".strip().lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print(json.dumps(run_parser_from_db(), ensure_ascii=False, indent=2))
