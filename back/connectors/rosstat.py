from datetime import datetime
from urllib.parse import unquote

from .generic import HtmlFilesConnector, clean_asset_title, is_meaningful_asset_title


class RosstatConnector(HtmlFilesConnector):
    name = "rosstat"

    def parse(self, source, config):
        config = {
            **config,
            "verify_ssl": False,
            "link_selector": "a[href]",
            "url_contains": ["/storage/mediabank/"],
            "file_extensions": [".xls", ".xlsx", ".csv", ".zip", ".pdf", ".doc", ".docx"],
            "require_date": False,
            "strict_dates": False,
            "max_age_days": 36500,
            "max_age_hours": None,
            "max_links": 120,
        }
        items = super().parse(source, config)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item in items:
            raw_data = item.get("raw_data") or {}
            if item.get("published_at"):
                raw_data["site_published_at"] = item["published_at"]
            item["published_at"] = now
            item["raw_data"] = raw_data
            self.format_rosstat_file_event(item)
        return items

    def format_rosstat_file_event(self, item):
        raw_data = item.get("raw_data") or {}
        document_title = clean_asset_title(item.get("title") or "")
        if not is_meaningful_asset_title(document_title):
            document_title = clean_asset_title(unquote(item["url"].rsplit("/", 1)[-1]))
        asset_type = (raw_data.get("asset_type") or "").upper() or "ФАЙЛ"
        site_published_at = raw_data.get("site_published_at")

        item["title"] = f"Росстат: появился файл - {document_title}"
        item["text"] = "\n".join(
            part
            for part in [
                "На сайте Росстата появился файл.",
                f"Название: {document_title}",
                f"Тип: {asset_type}",
                f"Дата на сайте: {site_published_at}" if site_published_at else None,
                f"Ссылка: {item['url']}",
            ]
            if part
        )
        raw_data.update({
            "event_type": "rosstat_file_published",
            "document_title": document_title,
            "document_type": asset_type,
        })
        item["raw_data"] = raw_data
