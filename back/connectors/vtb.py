from urllib.parse import urlencode

from .base import BaseConnector


class VtbConnector(BaseConnector):
    name = "vtb"

    API_URL = "https://siteapi.vtb.ru/api/news/v2/newsArticles"

    def parse(self, source, config):
        params = {
            "category": "press-releases",
            "count": int(config.get("max_links") or 18),
            "projectSysName": "vtb.ru",
        }
        response = self.fetch(f"{self.API_URL}?{urlencode(params)}", config)
        payload = response.json()
        records = payload.get("news") or payload.get("items") or []

        items = []
        for record in records:
            published_at = self.normalize_published_at(
                record.get("createDate") or record.get("publishDate")
            )
            if not self.is_recent(published_at, config):
                continue

            title = self.html_to_text(record.get("title")) or source["name"]
            text = self.html_to_text(
                record.get("text")
                or record.get("description")
                or record.get("lead")
                or title
            )
            item_url = self.make_item_url(record)
            items.append(self.make_news_item(item_url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "api_url": self.API_URL,
                "api_id": record.get("id"),
                "category": record.get("category"),
                "publish_date": record.get("publishDate"),
            }))

        return items

    def make_item_url(self, record):
        path = record.get("url") or "/about/press/news"
        if not str(path).startswith("http"):
            path = f"https://www.vtb.ru{path}"
        if record.get("id"):
            return f"{path}?id={record['id']}"
        return path
