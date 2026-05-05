import re

from bs4 import BeautifulSoup

from .base import BaseConnector


class AlfabankConnector(BaseConnector):
    name = "alfabank"

    DATE_PREFIX_RE = re.compile(r"^\s*(\d{1,2}\s+[а-яА-ЯёЁ]+\s+20\d{2})\s+(.+)$")

    def parse(self, source, config):
        config = {**config, "use_firecrawl_on_block": True}
        response = self.fetch(source["url"], config)
        soup = BeautifulSoup(response.text, "lxml")
        items = []
        seen = set()
        existing_urls = config.get("_existing_urls") or set()
        max_links = int(config.get("max_links") or 80)

        for link in soup.select("a[href*='/news/t/release/'], a[href*='/news/t/']"):
            href = link.get("href")
            if not href:
                continue
            url = self.normalize_url(href, source["url"])
            if url in seen:
                continue
            seen.add(url)
            if url in existing_urls:
                continue

            parsed = self.parse_listing_title(self.html_to_text(link.get_text(" ", strip=True)))
            if not parsed:
                continue

            published_at, title = parsed
            if not self.is_recent(published_at, config):
                continue

            text, text_source = self.fetch_article_text(url, title, config)
            items.append(self.make_news_item(url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "text_source": text_source,
            }))
            if len(items) >= max_links:
                break

        return items

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
            text = self.extract_alfa_text(soup, title)
            if len(text) >= 200:
                return text, "article_firecrawl"
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
