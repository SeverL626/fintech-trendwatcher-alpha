import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseConnector


class SberConnector(BaseConnector):
    name = "sber"

    ARTICLE_MARKER = "/news-and-media/press-releases/article"

    def parse(self, source, config):
        config = {**config, "use_firecrawl_on_block": True}
        response = self.fetch(source["url"], config)
        soup = BeautifulSoup(response.text, "lxml")
        items = []
        seen = set()
        existing_urls = config.get("_existing_urls") or set()
        max_links = int(config.get("max_links") or 60)
        max_article_fetches = int(config.get("max_article_fetches") or max_links)

        for link in soup.find_all("a", href=True):
            href = link.get("href")
            if self.ARTICLE_MARKER not in href:
                continue
            url = urljoin(source["url"], href)
            if url in seen:
                continue
            seen.add(url)
            if url in existing_urls:
                continue

            title = self.html_to_text(link.get_text(" ", strip=True))
            published_at = self.extract_card_date(link, title)
            if not title or not self.is_recent(published_at, config):
                continue

            if len(items) < max_article_fetches:
                text, text_source = self.fetch_article_text(url, title, config)
            else:
                text, text_source = self.make_listing_text(title, url), "listing_fallback"

            items.append(self.make_news_item(url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "text_source": text_source,
            }))
            if len(items) >= max_links:
                break

        return items

    def extract_card_date(self, link, title):
        card = link.find_parent(class_=lambda value: value and "news-archive-list__article" in value)
        raw_text = self.html_to_text(card.get_text(" ", strip=True) if card else "")
        label = raw_text.replace(title, "", 1).strip()

        now = datetime.now()
        if label.startswith("Сегодня"):
            return now.strftime("%Y-%m-%d %H:%M:%S")
        if label.startswith("Вчера"):
            return (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")

        match = re.search(r"\b\d{1,2}\s+[а-яА-ЯёЁ]+\s+20\d{2}\b", label)
        if match:
            return self.normalize_published_at(match.group(0))
        return None

    def fetch_article_text(self, url, title, config):
        try:
            response = self.fetch(url, config)
            soup = BeautifulSoup(response.text, "lxml")
            text = self.extract_sber_text(soup)
            if len(text) >= 200:
                return text, "article_firecrawl"
        except Exception:
            pass
        return self.make_listing_text(title, url), "listing_fallback"

    def extract_sber_text(self, soup):
        selectors = [
            "[class*='article'] p",
            "[class*='news'] p",
            "p",
        ]
        parts = []
        seen = set()
        for selector in selectors:
            for element in soup.select(selector):
                text = self.html_to_text(element.get_text(" ", strip=True))
                if not text or text in seen:
                    continue
                seen.add(text)
                parts.append(text)
            if parts:
                break
        return "\n\n".join(parts).strip()

    def make_listing_text(self, title, url):
        return "\n".join([
            "На сайте Сбера опубликован пресс-релиз.",
            f"Заголовок: {title}",
            f"Ссылка: {url}",
        ])
