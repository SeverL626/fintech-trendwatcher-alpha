from __future__ import annotations

import re
import html as html_lib
import os
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import dateparser
import requests
from bs4 import BeautifulSoup
from requests.models import Response

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass


DEFAULT_LOOKBACK_DAYS = 1
DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class BaseConnector:
    name = "base"

    def parse(self, source, config):
        raise NotImplementedError(f"Connector {self.name} is not implemented")

    def fetch(self, url, config):
        headers = {"User-Agent": config.get("user_agent") or DEFAULT_USER_AGENT}
        verify_ssl = config.get("verify_ssl", True)
        if not verify_ssl:
            disable_insecure_request_warning()

        response = requests.get(
            url,
            headers=headers,
            timeout=config.get("timeout") or 15,
            verify=verify_ssl,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            if response.status_code in (403, 429):
                return self.fetch_with_firecrawl(url, config, str(error))
            raise
        self.fix_response_encoding(response)
        try:
            self.raise_if_blocked(response, url)
        except BlockedRequestError as error:
            return self.fetch_with_firecrawl(url, config, str(error))
        return response

    def fix_response_encoding(self, response):
        content_type = response.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type and "xml" not in content_type:
            return
        current = (response.encoding or "").lower()
        apparent = response.apparent_encoding
        if current in ("iso-8859-1", "windows-1252", "ascii") and apparent:
            response.encoding = apparent

    def parse_date(self, value):
        if not value:
            return None

        normalized = str(value).strip()
        parsed = self.parse_iso_like_date(normalized)
        if parsed:
            return parsed

        parsed = dateparser.parse(
            normalized,
            languages=["ru", "en"],
            settings={
                "PREFER_DATES_FROM": "past",
                "DATE_ORDER": "DMY",
            },
        )
        if not parsed:
            return None
        if parsed.tzinfo:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed.replace(tzinfo=None)

    def parse_iso_like_date(self, value):
        match = re.search(
            r"(?P<date>\d{4}[-/]\d{2}[-/]\d{2})"
            r"(?:[T\s](?P<time>\d{2}:\d{2}(?::\d{2})?))?"
            r"(?P<tz>Z|[+-]\d{2}:?\d{2})?",
            value,
        )
        if not match:
            return None

        date_part = match.group("date").replace("/", "-")
        time_part = match.group("time") or "00:00:00"
        if len(time_part) == 5:
            time_part = f"{time_part}:00"
        tz_part = match.group("tz") or ""
        if tz_part == "Z":
            tz_part = "+00:00"
        elif tz_part and ":" not in tz_part:
            tz_part = f"{tz_part[:3]}:{tz_part[3:]}"

        try:
            parsed = datetime.fromisoformat(f"{date_part}T{time_part}{tz_part}")
        except ValueError:
            return None

        if parsed.tzinfo:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    def normalize_published_at(self, value):
        parsed = self.parse_date(value)
        return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else None

    def is_recent(self, published_at, config):
        if not published_at:
            return not config.get("strict_dates", True)

        parsed = self.parse_date(published_at)
        if not parsed:
            return not config.get("strict_dates", True)

        max_future_hours = int(config.get("max_future_hours") or 2)
        now = datetime.now()
        if parsed > now + timedelta(hours=max_future_hours):
            return False

        if config.get("max_age_hours") is not None:
            max_age_hours = int(config["max_age_hours"])
            return parsed >= now - timedelta(hours=max_age_hours)

        max_age_days = int(config.get("max_age_days") or DEFAULT_LOOKBACK_DAYS)
        return parsed >= now - timedelta(days=max_age_days)

    def html_to_text(self, value):
        if not value:
            return ""
        text = str(value)
        for _ in range(2):
            unescaped = html_lib.unescape(text)
            if unescaped == text:
                break
            text = unescaped
        return " ".join(
            BeautifulSoup(text, "lxml")
            .get_text(" ", strip=True)
            .replace("\xa0", " ")
            .split()
        )

    def raise_if_blocked(self, response, url):
        content_type = response.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type:
            return

        sample = response.text[:5000].lower()
        waf_markers = (
            "user_blocked",
            "servicepipe.ru",
            "captcha",
            "cloudflare",
            "if you are not a bot",
            "request rejected",
            "access denied",
        )
        if any(marker in sample for marker in waf_markers):
            raise BlockedRequestError(
                f"{url} blocked automated requests; use browser rendering or Firecrawl"
            )

    def fetch_with_firecrawl(self, url, config, reason):
        if not config.get("use_firecrawl_on_block"):
            raise BlockedRequestError(reason)

        api_key = config.get("firecrawl_api_key") or os.getenv("FIRECRAWL_API_KEY")
        if not api_key:
            raise BlockedRequestError(
                f"{reason}; set FIRECRAWL_API_KEY to render this source via Firecrawl"
            )

        response = requests.post(
            "https://api.firecrawl.dev/v2/scrape",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "url": url,
                "formats": ["html"],
                "onlyMainContent": False,
            },
            timeout=config.get("firecrawl_timeout") or 60,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        body = ""
        if isinstance(data, dict):
            body = data.get("html") or data.get("rawHtml") or data.get("markdown") or ""
        if not body:
            raise RuntimeError(f"Firecrawl returned empty content for {url}")

        rendered = Response()
        rendered.status_code = 200
        rendered.url = url
        rendered.encoding = "utf-8"
        rendered._content = str(body).encode("utf-8")
        rendered.headers["content-type"] = "text/html; charset=utf-8"
        return rendered

    def local_name(self, tag):
        return str(tag).rsplit("}", 1)[-1].split(":", 1)[-1]

    def child_text(self, element, names):
        normalized_names = {self.local_name(name).lower() for name in names}
        for child in element.iter():
            if child is element:
                continue
            if self.local_name(child.tag).lower() in normalized_names:
                text = child.text or child.get("href") or child.get("content")
                if text:
                    return text.strip()
        return None

    def parse_xml(self, body):
        return ElementTree.fromstring(body)

    def make_news_item(self, url, title, published_at, text, raw_data):
        return {
            "url": url,
            "title": title,
            "published_at": published_at,
            "text": text or title or url,
            "raw_data": raw_data,
        }

    def normalize_url(self, href, base_url):
        url = urljoin(base_url, href)
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def extract_canonical_url(self, soup, fallback_url):
        canonical = soup.select_one("link[rel='canonical']")
        if canonical and canonical.get("href"):
            return canonical.get("href")
        og_url = soup.select_one("meta[property='og:url']")
        if og_url and og_url.get("content"):
            return og_url.get("content")
        return fallback_url

    def extract_title(self, soup, fallback=None):
        selectors = [
            "meta[property='og:title']",
            "h1",
            "title",
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            if element.name == "meta":
                value = element.get("content")
            else:
                value = element.get_text(" ", strip=True)
            if value:
                return value.strip()
        return fallback

    def extract_published_at(self, soup):
        selectors = [
            "meta[property='article:published_time']",
            "meta[name='pubdate']",
            "time[datetime]",
            ".article__header__date",
            ".article__date",
            ".date",
        ]
        for selector in selectors:
            element = soup.select_one(selector)
            if not element:
                continue
            if element.name == "meta":
                value = element.get("content")
            elif element.name == "time":
                value = element.get("datetime") or element.get_text(" ", strip=True)
            else:
                value = element.get_text(" ", strip=True)
            published_at = self.normalize_published_at(value)
            if published_at:
                return published_at
        return None

    def extract_article_text(self, soup, selectors=None):
        selectors = selectors or [
            "article p",
            "main p",
            ".article__text p",
            ".article__body p",
            "[itemprop='articleBody'] p",
        ]

        parts = []
        seen = set()
        for selector in selectors:
            for element in soup.select(selector):
                text = element.get_text(" ", strip=True)
                if not text or text in seen:
                    continue
                seen.add(text)
                parts.append(text)
            if len(" ".join(parts)) >= 500:
                break

        if parts:
            return "\n\n".join(parts)

        meta_description = soup.select_one("meta[property='og:description']")
        if meta_description and meta_description.get("content"):
            return meta_description.get("content")

        return None

    def parse_article_page(self, url, config, fallback_title=None, fallback_published_at=None):
        response = self.fetch(url, config)
        soup = BeautifulSoup(response.text, "lxml")
        text_selectors = config.get("text_selectors") or config.get("text_selector")
        if isinstance(text_selectors, str):
            text_selectors = [text_selectors]
        return {
            "canonical_url": self.extract_canonical_url(soup, url),
            "title": self.extract_title(soup, fallback_title),
            "published_at": self.extract_published_at(soup) or fallback_published_at,
            "text": self.extract_article_text(soup, text_selectors),
        }


class NotImplementedConnector(BaseConnector):
    def __init__(self, name):
        self.name = name


class BlockedRequestError(RuntimeError):
    pass


def disable_insecure_request_warning():
    try:
        from urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    except Exception:
        pass
