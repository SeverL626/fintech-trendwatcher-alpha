from __future__ import annotations

import re
import html as html_lib
import json
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

import dateparser
import requests
from bs4 import BeautifulSoup


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
        headers = self.make_headers(config)
        verify_ssl = config.get("verify_ssl", True)
        if not verify_ssl:
            disable_insecure_request_warning()

        session = config.get("_session")
        requester = session.get if session else requests.get
        response = requester(
            url,
            headers=headers,
            timeout=config.get("timeout") or 15,
            verify=verify_ssl,
        )
        response.raise_for_status()
        self.fix_response_encoding(response)
        self.raise_if_blocked(response, url)
        return response

    def make_headers(self, config):
        headers = {
            "User-Agent": config.get("user_agent") or DEFAULT_USER_AGENT,
            "Accept": config.get("accept")
            or "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": config.get("accept_language") or "ru-RU,ru;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if config.get("referer"):
            headers["Referer"] = config["referer"]
        headers.update(config.get("headers") or {})
        return headers

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
            "cloudflare",
            "if you are not a bot",
            "request rejected",
            "access denied",
            "please enable javascript",
            "dosl7.challenge",
            "window[\"bobcmn\"]",
            "/tspd/",
        )
        if any(marker in sample for marker in waf_markers):
            raise BlockedRequestError(
                f"{url} blocked automated requests"
            )

    def fetch_reader_text(self, url, config):
        last_error = None
        for reader_url in self.reader_urls(url):
            try:
                response = requests.get(
                    reader_url,
                    headers={
                        "User-Agent": config.get("user_agent") or DEFAULT_USER_AGENT,
                        "Accept": "text/plain,*/*;q=0.8",
                        "Accept-Language": config.get("accept_language") or "ru-RU,ru;q=0.9,en;q=0.8",
                        "x-no-cache": "true",
                    },
                    timeout=config.get("reader_timeout") or 30,
                )
                response.raise_for_status()
                self.fix_response_encoding(response)
                text = response.text.strip()
                if text and not self.reader_text_is_blocked(text):
                    return text
            except Exception as error:
                last_error = error
        if last_error:
            raise last_error
        raise RuntimeError(f"Jina Reader returned empty content for {url}")

    def reader_urls(self, url):
        urls = [f"https://r.jina.ai/{url}"]
        if url.startswith("https://"):
            urls.append(f"https://r.jina.ai/http://r.jina.ai/http://{url}")
        return urls

    def reader_text_is_blocked(self, text):
        lowered = text.lower()
        return (
            "requiring captcha" in lowered
            or "securitycompromiseerror" in lowered
            or "anonymous access to domain" in lowered
        )

    def clean_reader_text(self, raw_text, title=None):
        lines = []
        capture = not title
        title_normalized = " ".join(str(title or "").lower().split())
        skip_prefixes = (
            "Title:",
            "URL Source:",
            "Markdown Content:",
            "Published Time:",
            "Warning:",
        )
        for raw_line in str(raw_text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(skip_prefixes):
                continue
            normalized = " ".join(line.lower().split())
            if title_normalized and title_normalized in normalized:
                capture = True
                continue
            if capture:
                lines.append(line)
        return self.html_to_text("\n\n".join(lines))

    def extract_json_ld_text(self, soup):
        parts = []
        for script in soup.select("script[type='application/ld+json']"):
            raw = script.string or script.get_text()
            if not raw:
                continue
            try:
                payload = html_lib.unescape(raw)
                data = json.loads(payload)
            except Exception:
                continue
            parts.extend(self.extract_json_text_values(data))
        return "\n\n".join(unique_texts(parts)).strip()

    def extract_json_text_values(self, data):
        values = []
        if isinstance(data, list):
            for item in data:
                values.extend(self.extract_json_text_values(item))
            return values
        if not isinstance(data, dict):
            return values

        for key in ("articleBody", "description", "text"):
            value = data.get(key)
            if isinstance(value, str) and len(value.strip()) >= 80:
                values.append(self.html_to_text(value))
        for value in data.values():
            if isinstance(value, (dict, list)):
                values.extend(self.extract_json_text_values(value))
        return values

    def extract_embedded_json_text(self, soup):
        parts = []
        patterns = (
            r'"articleBody"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"',
            r'"description"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"',
        )
        for script in soup.select("script"):
            raw = script.string or script.get_text()
            if not raw or len(raw) < 200:
                continue
            for pattern in patterns:
                for match in re.finditer(pattern, raw):
                    value = match.group("value")
                    try:
                        decoded = value.encode("utf-8").decode("unicode_escape")
                    except UnicodeDecodeError:
                        decoded = value
                    text = self.html_to_text(decoded)
                    if len(text) >= 80:
                        parts.append(text)
        return "\n\n".join(unique_texts(parts)).strip()

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
            "meta[property='article:modified_time']",
            "meta[name='pubdate']",
            "meta[name='date']",
            "meta[name='parsely-pub-date']",
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
        full_text = soup.get_text(" ", strip=True)
        for pattern in (
            r"Дата публикации:\s*\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2})?",
            r"\b\d{1,2}\.\d{1,2}\.\d{4}(?:\s+\d{1,2}:\d{2})?\b",
            r"\b\d{1,2}\s+[A-Za-z]+\s+20\d{2}(?:\s+\d{1,2}:\d{2})?\b",
            r"\b[A-Za-z]+\s+\d{1,2},\s+20\d{2}(?:\s+\d{1,2}:\d{2})?\b",
        ):
            match = re.search(pattern, full_text)
            if not match:
                continue
            raw_date = match.group(0).replace("Дата публикации:", "").strip()
            published_at = self.normalize_published_at(raw_date)
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


def unique_texts(values):
    result = []
    seen = set()
    for value in values:
        text = " ".join(str(value or "").split())
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def disable_insecure_request_warning():
    try:
        from urllib3.exceptions import InsecureRequestWarning

        requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)
    except Exception:
        pass
