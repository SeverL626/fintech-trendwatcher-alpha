import json
import re
from datetime import datetime
from urllib.parse import unquote

from bs4 import BeautifulSoup

from .base import BaseConnector


class RssConnector(BaseConnector):
    name = "rss"

    def parse(self, source, config):
        response = self.fetch(source["url"], config)
        root = self.parse_xml(response.content)
        items = []
        seen = set()
        max_items = int(config.get("max_items") or config.get("max_links") or 80)

        for element in root.iter():
            if self.local_name(element.tag) != "item":
                continue

            title = self.child_text(element, ["title"]) or source["name"]
            url = self.child_text(element, ["link", "guid"]) or source["url"]
            if url in seen:
                continue
            seen.add(url)

            published_at = self.normalize_published_at(
                self.child_text(element, ["pubDate", "dc:date", "date"])
            )
            if not self.is_recent(published_at, config):
                continue

            rss_description = self.html_to_text(
                self.child_text(element, ["description", "content:encoded", "summary"])
                or title
            )
            article = self.fetch_article(url, title, published_at, config)
            article_text = article.get("text")
            use_article_text = bool(article_text and len(article_text) > len(rss_description))
            items.append(self.make_news_item(
                article.get("canonical_url") or url,
                article.get("title") or title,
                article.get("published_at") or published_at,
                article_text if use_article_text else rss_description,
                {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "rss_description": rss_description,
                    "text_source": "article_html" if use_article_text else "rss_description_fallback",
                    "article_error": article.get("error"),
                },
            ))
            if len(items) >= max_items:
                break

        return items

    def fetch_article(self, url, title, published_at, config):
        if not config.get("fetch_article_text", True):
            return {
                "canonical_url": url,
                "title": title,
                "published_at": published_at,
                "text": None,
                "error": None,
            }
        try:
            return {
                **self.parse_article_page(url, config, title, published_at),
                "error": None,
            }
        except Exception as error:
            return {
                "canonical_url": url,
                "title": title,
                "published_at": published_at,
                "text": None,
                "error": str(error),
            }


class XmlNewsConnector(BaseConnector):
    name = "xml_news"

    def parse(self, source, config):
        response = self.fetch(source["url"], config)
        root = self.parse_xml(response.content)
        items = []
        item_tags = set(config.get("item_tags") or ["Item", "News", "Record"])

        for element in root.iter():
            if self.local_name(element.tag) not in item_tags:
                continue

            title = self.child_text(element, config.get("title_fields") or ["Title", "title", "Name", "name"])
            title = title or source["name"]
            url = self.child_text(element, config.get("url_fields") or ["Url", "URL", "Link", "link"])
            url = self.normalize_url(url or source["url"], config.get("url_prefix") or source["url"])
            published_at = self.normalize_published_at(
                self.child_text(element, config.get("date_fields") or ["Date", "date"])
            )
            if not self.is_recent(published_at, config):
                continue

            text = self.html_to_text(
                self.child_text(element, config.get("text_fields") or ["Text", "Description", "text"])
                or title
            )
            items.append(self.make_news_item(url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "xml_tag": self.local_name(element.tag),
            }))

        return items


class HtmlConnector(BaseConnector):
    name = "html"

    def parse(self, source, config):
        response = self.fetch(source["url"], config)
        soup = BeautifulSoup(response.text, "lxml")
        selector = config.get("link_selector") or "a[href]"
        max_links = int(config.get("max_links") or 80)
        items = []
        seen = set()

        for link in soup.select(selector):
            href = link.get("href")
            if not href:
                continue
            url = self.normalize_url(href, source["url"])
            if url in seen:
                continue
            seen.add(url)

            if not self.is_allowed_url(url, config):
                continue

            title = link.get_text(" ", strip=True) or source["name"]
            listing_published_at = self.extract_date_from_text(
                self.extract_listing_context(link)
            )
            try:
                article = self.parse_article_page(url, config, title, listing_published_at)
            except Exception as error:
                items.append(self.make_news_item(url, title, None, title, {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "article_error": str(error),
                }))
                continue

            published_at = article.get("published_at")
            if config.get("require_date") and not published_at:
                continue
            if not self.is_recent(published_at, config):
                continue

            items.append(self.make_news_item(
                article.get("canonical_url") or url,
                title if config.get("prefer_listing_title") else article.get("title") or title,
                published_at,
                article.get("text") or title,
                {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "text_source": "article_html",
                },
            ))

            if len(items) >= max_links:
                break

        return items

    def is_allowed_url(self, url, config):
        url_contains = config.get("url_contains") or []
        if not url_contains:
            return True
        return any(marker in url for marker in url_contains)

    def extract_listing_context(self, link):
        parts = [link.get_text(" ", strip=True)]
        parent = link.parent
        for _ in range(3):
            if not parent or not getattr(parent, "get_text", None):
                break
            text = parent.get_text(" ", strip=True)
            if text and len(text) <= 700:
                parts.append(text)
            parent = parent.parent
        return " ".join(parts)

    def extract_date_from_text(self, text):
        text = str(text or "")
        patterns = (
            r"\b\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2})?\b",
            r"\b\d{1,2}\s+[A-Za-zА-Яа-яёЁ]+\s+20\d{2}\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            published_at = self.normalize_published_at(match.group(0))
            if published_at:
                return published_at
        return None


class HtmlFilesConnector(HtmlConnector):
    name = "html_files"

    def parse(self, source, config):
        response = self.fetch(source["url"], config)
        soup = BeautifulSoup(response.text, "lxml")
        selector = config.get("link_selector") or "a[href]"
        file_extensions = tuple(config.get("file_extensions") or [".pdf", ".xls", ".xlsx", ".csv", ".zip"])
        max_links = int(config.get("max_links") or 80)
        items = []
        seen = set()

        for link in soup.select(selector):
            href = link.get("href")
            if not href:
                continue
            url = self.normalize_url(href, source["url"])
            lowered = url.lower()
            is_file = lowered.endswith(file_extensions)
            if not is_file and not self.is_allowed_url(url, config):
                continue
            if url in seen:
                continue
            seen.add(url)

            title = self.extract_link_title(link, url, source)
            published_at = self.extract_date_from_text(title)
            if config.get("require_date") and not published_at:
                continue
            if not self.is_recent(published_at, config):
                continue
            asset_type = url.rsplit(".", 1)[-1].lower() if "." in url else "html"
            items.append(self.make_news_item(url, title, published_at, f"Найден файл или ссылка: {url}", {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "asset_url": url,
                "asset_type": asset_type,
            }))

            if len(items) >= max_links:
                break

        return items

    def extract_link_title(self, link, url, source):
        text = link.get_text(" ", strip=True)
        if is_meaningful_asset_title(text):
            return text

        for parent in link.parents:
            if not getattr(parent, "get_text", None):
                continue
            parent_text = parent.get_text(" ", strip=True)
            if len(parent_text) > 180:
                continue
            if is_meaningful_asset_title(parent_text):
                return clean_asset_title(parent_text)

        filename = unquote(url.rsplit("/", 1)[-1])
        return filename or source["name"]

class MoexStatsConnector(BaseConnector):
    name = "moex"

    def parse(self, _source, _config):
        return []

    def parse_market_stats(self, source, config):
        response = self.fetch(source["url"], config)
        payload = response.json()
        records = self.extract_records(payload)
        max_items = int(config.get("max_items") or 200)
        today = datetime.now().strftime("%Y-%m-%d")
        names_by_secid = self.extract_security_names(records)
        preferred_records = [
            record
            for record in records
            if record.get("_table") == "marketdata"
        ] or records
        market_records = []

        for record in preferred_records:
            secid = value_from_keys(record, ["SECID", "secid"])
            if not secid:
                continue
            names = names_by_secid.get(secid, {})
            market_records.append({
                "secid": secid,
                "boardid": value_from_keys(record, ["BOARDID", "boardid"]),
                "shortname": value_from_keys(record, ["SHORTNAME", "shortname"]) or names.get("shortname"),
                "secname": value_from_keys(record, ["SECNAME", "secname"]) or names.get("secname"),
                "trade_date": moex_trade_date(record) or today,
                "last": to_float(value_from_keys(record, ["LAST", "last"])),
                "marketprice": to_float(value_from_keys(
                    record,
                    ["MARKETPRICETODAY", "MARKETPRICE", "marketprice", "MARKETPRICE2"],
                )),
                "open": to_float(value_from_keys(record, ["OPEN", "open"])),
                "high": to_float(value_from_keys(record, ["HIGH", "high"])),
                "low": to_float(value_from_keys(record, ["LOW", "low"])),
                "value": to_float(value_from_keys(record, ["VALTODAY_RUR", "VALTODAY", "VALUE", "value"])),
                "value_usd": to_float(value_from_keys(record, ["VALTODAY_USD", "VALUE_USD"])),
                "volume": to_float(value_from_keys(record, ["VOLTODAY", "VOLUME", "volume"])),
                "numtrades": to_int(value_from_keys(record, ["NUMTRADES", "numtrades"])),
                "systime": value_from_keys(record, ["SYSTIME", "systime"]),
                "raw_data": record,
            })

        if not market_records:
            return []

        return [self.aggregate_daily_stats(market_records[:max_items], today)]

    def extract_security_names(self, records):
        names = {}
        for record in records:
            if record.get("_table") != "securities":
                continue
            secid = value_from_keys(record, ["SECID", "secid"])
            if not secid:
                continue
            names[secid] = {
                "shortname": value_from_keys(record, ["SHORTNAME", "shortname"]),
                "secname": value_from_keys(record, ["SECNAME", "secname"]),
            }
        return names

    def aggregate_daily_stats(self, records, fallback_date):
        trade_date = next((record.get("trade_date") for record in records if record.get("trade_date")), fallback_date)
        value_records = [record for record in records if record.get("value") is not None]
        volume_records = [record for record in records if record.get("volume") is not None]
        trades_records = [record for record in records if record.get("numtrades") is not None]
        last_values = [record["last"] for record in records if record.get("last") is not None]
        market_prices = [
            record["marketprice"]
            for record in records
            if record.get("marketprice") is not None
        ]
        top_record = max(value_records, key=lambda record: record.get("value") or 0, default=None)
        top_volume_record = max(volume_records, key=lambda record: record.get("volume") or 0, default=None)
        top_trades_record = max(trades_records, key=lambda record: record.get("numtrades") or 0, default=None)

        return {
            "trade_date": trade_date,
            "securities_count": len({record["secid"] for record in records}),
            "traded_securities_count": sum(1 for record in records if record.get("numtrades") or record.get("value") or record.get("volume")),
            "total_value": sum(record.get("value") or 0 for record in records),
            "total_value_usd": sum(record.get("value_usd") or 0 for record in records),
            "total_volume": sum(record.get("volume") or 0 for record in records),
            "total_trades": sum(record.get("numtrades") or 0 for record in records),
            "average_last": average(last_values),
            "average_marketprice": average(market_prices),
            "top_secid": top_record.get("secid") if top_record else None,
            "top_shortname": top_record.get("shortname") if top_record else None,
            "top_value": top_record.get("value") if top_record else None,
            "top_volume_secid": top_volume_record.get("secid") if top_volume_record else None,
            "top_volume_shortname": top_volume_record.get("shortname") if top_volume_record else None,
            "top_volume": top_volume_record.get("volume") if top_volume_record else None,
            "top_trades_secid": top_trades_record.get("secid") if top_trades_record else None,
            "top_trades_shortname": top_trades_record.get("shortname") if top_trades_record else None,
            "top_trades": top_trades_record.get("numtrades") if top_trades_record else None,
            "moex_systime": max((record.get("systime") for record in records if record.get("systime")), default=None),
            "raw_data": {
                "records": records,
                "aggregation": "one_row_per_trade_date",
            },
        }

    def extract_records(self, payload):
        records = []
        if not isinstance(payload, dict):
            return records

        for table_name, table in payload.items():
            if not isinstance(table, dict):
                continue
            columns = table.get("columns")
            rows = table.get("data")
            if not isinstance(columns, list) or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, list):
                    continue
                record = dict(zip(columns, row))
                record["_table"] = table_name
                records.append(record)
        return records


def value_from_keys(record, keys):
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        value = record.get(key)
        if value is None:
            value = lowered.get(str(key).lower())
        if value not in (None, ""):
            return value
    return None


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def moex_trade_date(record):
    value = value_from_keys(record, ["TRADEDATE", "tradedate", "SYSTIME", "systime"])
    if not value:
        return None
    value = str(value).strip()
    if len(value) >= 10 and value[4:5] == "-" and value[7:8] == "-":
        return value[:10]
    return None


def average(values):
    if not values:
        return None
    return sum(values) / len(values)


def is_meaningful_asset_title(text):
    if not text:
        return False
    normalized = clean_asset_title(text).lower()
    if len(normalized) < 4:
        return False
    return normalized not in {
        "pdf",
        "xls",
        "xlsx",
        "csv",
        "zip",
        "html",
        "web",
        "скачать",
        "call_made",
        "call_made web",
        "open_in_new",
        "open_in_new web",
    }


def clean_asset_title(text):
    return " ".join(
        str(text)
        .replace("\ue2c0", " ")
        .replace("call_made", " ")
        .replace("open_in_new", " ")
        .replace("\xa0", " ")
        .split()
    )
