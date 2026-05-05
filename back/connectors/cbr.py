import requests

from .generic import RssConnector


class CbrConnector(RssConnector):
    name = "cbr"

    def parse(self, source, config):
        config = {
            **config,
            "text_selectors": [
                "article p",
                "main p",
                ".landing-text p",
                ".news_detail p",
            ],
            "fetch_article_text": False,
        }
        return super().parse(source, config)


class CbrNewsConnector(CbrConnector):
    name = "cbr_news"

    def parse(self, source, config):
        params = {
            "page": 0,
            "IsEng": "false",
            "dateFrom": "",
            "dateTo": "",
            "Tid": "",
            "phrase": "",
            "pagesize": int(config.get("page_size") or config.get("max_links") or 50),
        }
        endpoint = config.get("endpoint") or "https://cbr.ru/news/new_ent/"
        response = self.fetch_json(endpoint, source["url"], config, params)
        items = []
        for record in response:
            title = self.html_to_text(record.get("name_doc") or source["name"])
            url = self.normalize_url(str(record.get("doc_htm") or "").strip(), source["url"])
            published_at = self.normalize_published_at(record.get("DT"))
            if not title or not self.is_recent(published_at, config):
                continue
            text = title
            if config.get("fetch_article_text", True):
                try:
                    article = self.parse_article_page(url, config, title, published_at)
                    text = article.get("text") or title
                    title = article.get("title") or title
                    url = article.get("canonical_url") or url
                except Exception:
                    pass
            items.append(self.make_news_item(url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "menu_title": record.get("MenuTitle"),
                "table_type": record.get("TBLType"),
                "dateupdate": record.get("dateupdate"),
                "raw_record": record,
            }))
            if len(items) >= int(config.get("max_links") or 50):
                break
        return items

    def fetch_json(self, endpoint, referer, config, params):
        config = {
            **config,
            "referer": referer,
            "accept": "application/json, text/javascript, */*; q=0.01",
            "headers": {
                **(config.get("headers") or {}),
                "X-Requested-With": "XMLHttpRequest",
            },
        }
        response = requests.get(
            endpoint,
            params=params,
            headers=self.make_headers(config),
            timeout=config.get("timeout") or 15,
            verify=config.get("verify_ssl", True),
        )
        response.raise_for_status()
        self.fix_response_encoding(response)
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Unexpected CBR news response: {payload}")
        return payload
