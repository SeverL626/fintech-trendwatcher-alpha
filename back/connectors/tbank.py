import re
from urllib.parse import urlencode

from .base import BaseConnector


class TbankConnector(BaseConnector):
    name = "tbank"

    API_URL = "https://cfg.tinkoff.ru/about/public/api/news/platform/v1/getArticles"

    def parse(self, source, config):
        params = {
            "pageOffset": 0,
            "pageSize": int(config.get("max_links") or 30),
            "lang": "ru-RU",
            "partTitle": "Новости",
        }
        response = self.fetch(f"{self.API_URL}?{urlencode(params)}", config)
        records = self.extract_records(response.json())

        items = []
        for record in records:
            published_at = self.extract_published_at(record)
            if not self.is_recent(published_at, config):
                continue

            title = self.html_to_text(record.get("title")) or source["name"]
            text = self.html_to_text(
                record.get("text")
                or record.get("content")
                or record.get("description")
                or record.get("shortDescription")
                or title
            )
            items.append(self.make_news_item(
                self.make_item_url(record, source),
                title,
                published_at,
                text,
                {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "api_url": self.API_URL,
                    "api_id": record.get("id"),
                    "slug": record.get("slug"),
                },
            ))

        return items

    def extract_records(self, payload):
        containers = [payload]
        if isinstance(payload, dict):
            containers.extend(
                value for value in payload.values() if isinstance(value, dict)
            )

        for container in containers:
            if not isinstance(container, dict):
                continue
            for key in ("items", "articles", "news", "data"):
                value = container.get(key)
                if isinstance(value, list):
                    return value
        return []

    def extract_published_at(self, record):
        for key in (
            "publishedAt",
            "publicationDate",
            "published_at",
            "publishDate",
            "createdAt",
            "date",
        ):
            published_at = self.normalize_published_at(record.get(key))
            if published_at:
                return published_at

        text = " ".join(str(record.get(key) or "") for key in ("dateLabel", "text", "title"))
        match = re.search(
            r"\b\d{1,2}\s+[а-яА-ЯёЁ]+\s+20\d{2}\b|\b\d{1,2}\.\d{1,2}\.20\d{2}\b",
            text,
        )
        return self.normalize_published_at(match.group(0)) if match else None

    def make_item_url(self, record, source):
        slug = record.get("slug")
        if slug:
            return f"https://www.tbank.ru/about/news/{slug}/"
        item_id = record.get("id")
        if item_id:
            return f"{source['url'].rstrip('/')}/?id={item_id}"
        return source["url"]
