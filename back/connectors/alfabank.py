import re
import requests

from bs4 import BeautifulSoup

from .base import BaseConnector
from .telegram import TelegramConnector


class AlfabankConnector(BaseConnector):
    name = "alfabank"

    DATE_PREFIX_RE = re.compile(r"^\s*(\d{1,2}\s+[а-яА-ЯёЁ]+\s+20\d{2})\s+(.+)$")
    READER_LINK_RE = re.compile(
        r"\[(?P<date>\d{1,2}\s+[а-яА-ЯёЁ]+\s+20\d{2})\s+#+\s*"
        r"(?P<title>.*?)\s*(?:\*\s*)*\]\((?P<url>https://alfabank\.ru/news/t/release/[^)]+)\)"
    )

    def parse(self, source, config):
        config = {**config, "referer": source["url"], "_session": requests.Session()}
        existing_urls = config.get("_existing_urls") or set()
        max_links = int(config.get("max_links") or 80)

        items = []
        seen = set()
        try:
            records = self.fetch_listing_records(source, config)
        except Exception:
            records = []

        for record in records:
            url = record["url"]
            if url in seen or url in existing_urls:
                continue
            seen.add(url)

            published_at = record["published_at"]
            title = record["title"]
            if not self.is_recent(published_at, config):
                continue

            text, text_source = self.fetch_article_text(url, title, config)
            if text_source == "listing_fallback" and config.get("skip_listing_fallback", True):
                continue
            items.append(self.make_news_item(url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "text_source": text_source,
            }))
            if len(items) >= max_links:
                break

        if config.get("use_telegram_fallback", True):
            items.extend(self.parse_official_telegram(source, config))
        return items

    def parse_official_telegram(self, source, config):
        telegram_source = {
            **source,
            "name": f"{source['name']} / Telegram: Альфа-Банк",
            "url": "https://t.me/alfabank",
        }
        telegram_config = {
            **config,
            "channel": "alfabank",
            "min_text_length": min(int(config.get("min_text_length") or 80), 20),
        }
        items = TelegramConnector().parse(telegram_source, telegram_config)
        for item in items:
            raw_data = item.get("raw_data") or {}
            raw_data.update({
                "adapter": self.name,
                "fallback_adapter": "telegram",
                "source": source["name"],
                "source_url": source["url"],
                "fallback_source_url": telegram_source["url"],
                "text_source": "official_telegram",
            })
            item["raw_data"] = raw_data
        return items

    def fetch_listing_records(self, source, config):
        try:
            response = self.fetch(source["url"], config)
            records = self.extract_html_listing(response.text, source["url"])
            if records:
                return records
        except Exception:
            pass
        if config.get("use_jina_reader", True):
            return self.extract_reader_listing(self.fetch_reader_text(source["url"], config))
        return []

    def extract_html_listing(self, html, base_url):
        soup = BeautifulSoup(html, "lxml")
        records = []
        for link in soup.select("a[href*='/news/t/release/'], a[href*='/news/t/']"):
            href = link.get("href")
            if not href:
                continue
            parsed = self.parse_listing_title(self.html_to_text(link.get_text(" ", strip=True)))
            if not parsed:
                continue
            published_at, title = parsed
            records.append({
                "url": self.normalize_url(href, base_url),
                "published_at": published_at,
                "title": title,
            })
        return records

    def extract_reader_listing(self, raw_text):
        records = []
        for match in self.READER_LINK_RE.finditer(raw_text):
            published_at = self.normalize_published_at(match.group("date"))
            title = self.html_to_text(match.group("title").replace("*", ""))
            url = self.normalize_url(match.group("url"), "https://alfabank.ru/news/t/")
            if published_at and title:
                records.append({
                    "url": url,
                    "published_at": published_at,
                    "title": title,
                })
        return records

    def parse_listing_title(self, raw_title):
        if not raw_title:
            return None
        match = self.DATE_PREFIX_RE.match(" ".join(raw_title.split()))
        if not match:
            return None
        published_at = self.normalize_published_at(match.group(1))
        title = match.group(2).strip()
        if not published_at or not title:
            return None
        return published_at, title

    def fetch_article_text(self, url, title, config):
        try:
            response = self.fetch(url, config)
            soup = BeautifulSoup(response.text, "lxml")
            text = (
                self.extract_alfa_text(soup, title)
                or self.extract_json_ld_text(soup)
                or self.extract_embedded_json_text(soup)
                or self.extract_article_text(soup)
            )
            if text and len(text) >= 200:
                return text, "article_html"
        except Exception:
            pass

        if config.get("use_jina_reader", True):
            try:
                text = self.clean_reader_text(self.fetch_reader_text(url, config), title)
                if len(text) >= 200:
                    return text, "article_jina_reader"
            except Exception:
                pass

        return self.make_listing_text(title, url), "listing_fallback"

    def extract_alfa_text(self, soup, title):
        paragraphs = [
            self.html_to_text(element.get_text(" ", strip=True))
            for element in soup.select("p")
        ]
        paragraphs = [paragraph for paragraph in paragraphs if paragraph]
        start_index = 0
        for index, paragraph in enumerate(paragraphs):
            if paragraph == title or title in paragraph:
                start_index = index + 1
                break

        parts = []
        stop_values = {"Поделитесь:", "Частным лицам", "Малому бизнесу", "Бизнесу"}
        for paragraph in paragraphs[start_index:]:
            if paragraph in stop_values:
                break
            if paragraph in {"Пресс-релизы", title}:
                continue
            parts.append(paragraph)
        return "\n\n".join(parts).strip()

    def make_listing_text(self, title, url):
        return "\n".join([
            "На сайте Альфа-Банка опубликован пресс-релиз.",
            f"Заголовок: {title}",
            f"Ссылка: {url}",
        ])
