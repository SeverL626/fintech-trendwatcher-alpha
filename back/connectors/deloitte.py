import re
import requests

from bs4 import BeautifulSoup

from .generic import HtmlConnector


class DeloitteInsightsConnector(HtmlConnector):
    name = "deloitte_insights"

    ARTICLE_MARKERS = ("Article", "Podcast", "Collection", "Magazine", "Report")
    SEARCH_ENDPOINT = "https://www.deloitte.com/modern-prod-english/_search"
    ARTICLE_PAGE_TYPES = ("insights-article",)

    def parse(self, source, config):
        candidates = self.fetch_search_candidates(source, config)
        if not candidates:
            candidates = self.fetch_listing_candidates(source, config)
        return self.parse_candidates(source, config, candidates)

    def fetch_search_candidates(self, source, config):
        page_size = int(config.get("search_page_size") or 100)
        max_pages = int(config.get("search_max_pages") or 3)
        candidates = []
        seen = set()

        for page in range(max_pages):
            payload = self.build_search_payload(page * page_size, page_size)
            try:
                response = requests.post(
                    self.SEARCH_ENDPOINT,
                    headers={
                        "User-Agent": config.get("user_agent"),
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "d-target": "elastic",
                    },
                    json=payload,
                    timeout=config.get("timeout") or 20,
                )
                response.raise_for_status()
                data = response.json()
            except Exception:
                return []

            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            page_has_recent = False
            for hit in hits:
                item = self.candidate_from_search_hit(source, hit)
                if not item:
                    continue
                if item["url"] in seen:
                    continue
                seen.add(item["url"])

                if self.is_recent(item.get("published_at"), config):
                    page_has_recent = True
                    candidates.append(item)

            if not page_has_recent:
                break

        return sorted(
            candidates,
            key=lambda item: self.parse_date(item.get("published_at")),
            reverse=True,
        )

    def build_search_payload(self, offset, size):
        return {
            "from": offset,
            "size": size,
            "_source": [
                "title",
                "promo-title",
                "url",
                "date-published",
                "page-description",
                "content-type",
                "page-type",
            ],
            "query": {
                "bool": {
                    "must": [
                        {"match_phrase": {"country-code": "us"}},
                        {"match_phrase": {"language": "en"}},
                        {
                            "bool": {
                                "should": [
                                    {"match_phrase": {"page-type": page_type}}
                                    for page_type in self.ARTICLE_PAGE_TYPES
                                ],
                                "minimum_should_match": 1,
                            }
                        },
                    ]
                }
            },
            "sort": [{"date-published": {"order": "desc"}}],
        }

    def candidate_from_search_hit(self, source, hit):
        payload = hit.get("_source") or {}
        url = payload.get("url")
        if not url:
            return None
        url = self.normalize_url(url, source["url"])
        if not self.is_article_url(url):
            return None
        return {
            "url": url,
            "title": payload.get("promo-title") or payload.get("title") or source["name"],
            "published_at": self.normalize_published_at(payload.get("date-published")),
            "description": payload.get("page-description") or "",
        }

    def fetch_listing_candidates(self, source, config):
        response = self.fetch(source["url"], config)
        soup = BeautifulSoup(response.text, "lxml")
        candidates = []
        seen = set()

        for link in soup.select("a[href*='/us/en/insights/']"):
            href = link.get("href")
            if not href:
                continue
            url = self.normalize_url(href, source["url"])
            if url in seen or not self.is_article_url(url):
                continue

            context = self.extract_listing_context(link)
            if not self.is_article_context(context):
                continue

            seen.add(url)
            listing_title = self.clean_listing_title(link.get_text(" ", strip=True))
            listing_published_at = self.extract_date_from_text(context)
            candidates.append({
                "url": url,
                "title": listing_title or source["name"],
                "published_at": listing_published_at,
                "description": context,
            })

        return candidates

    def parse_candidates(self, source, config, candidates):
        max_links = int(config.get("max_links") or 100)
        items = []
        existing_urls = set(config.get("_existing_urls") or ())

        for candidate in candidates:
            if len(items) >= max_links:
                break
            if candidate["url"] in existing_urls:
                continue
            try:
                article = self.parse_article_page(
                    candidate["url"],
                    config,
                    candidate.get("title"),
                    candidate.get("published_at"),
                )
            except Exception as error:
                items.append(self.make_news_item(candidate["url"], candidate.get("title") or source["name"], candidate.get("published_at"), candidate.get("description"), {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "text_source": "candidate_fallback",
                    "article_error": str(error),
                }))
                continue

            published_at = article.get("published_at")
            if config.get("require_date") and not published_at:
                continue
            if not self.is_recent(published_at, config):
                continue

            items.append(self.make_news_item(
                article.get("canonical_url") or candidate["url"],
                article.get("title") or candidate.get("title") or source["name"],
                published_at,
                article.get("text") or candidate.get("description") or candidate.get("title"),
                {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "text_source": "article_html",
                },
            ))

        return items

    def is_article_url(self, url):
        lowered = url.lower()
        if not lowered.endswith(".html"):
            return False
        return not any(marker in lowered for marker in (
            "/about.html",
            "/research-centers/",
            "/multimedia/videos.html",
            "/deloitte-insights-magazine.html",
            "/top-10-business-insights.html",
        ))

    def is_article_context(self, context):
        return any(marker in str(context or "") for marker in self.ARTICLE_MARKERS)

    def clean_listing_title(self, text):
        text = re.sub(r"\b(?:Article|Podcast|Collection|Magazine|Report)\s+.\s+\d+-min read\b", " ", str(text or ""))
        return " ".join(text.split())

    def parse_article_page(self, url, config, fallback_title=None, fallback_published_at=None):
        response = self.fetch(url, config)
        soup = BeautifulSoup(response.text, "lxml")
        return {
            "canonical_url": self.extract_canonical_url(soup, url),
            "title": self.extract_title(soup, fallback_title),
            "published_at": self.extract_published_at(soup) or fallback_published_at,
            "text": self.extract_deloitte_article_text(soup, config),
        }

    def extract_deloitte_article_text(self, soup, config=None):
        h1 = soup.select_one("h1")
        if not h1:
            return self.extract_article_text(soup, ["article p", "main p"])

        parts = []
        seen = set()
        body_started = False
        subtitle_added = False
        title = self.normalize_text(h1.get_text(" ", strip=True))

        for element in h1.find_all_next():
            marker_text = self.normalize_text(element.get_text(" ", strip=True))
            if (
                not body_started
                and element.name in {"time", "span", "div", "p", "li"}
                and len(marker_text) <= 160
                and self.extract_date_from_text(marker_text)
            ):
                body_started = True
                continue

            text = marker_text if element.name in {"h2", "h3", "h4", "p", "li"} else ""
            text = self.normalize_text(text)
            if not text:
                continue
            if text == title or text in seen:
                continue
            if self.is_stop_text(text):
                if body_started:
                    break
                continue
            if self.is_metadata_text(text):
                continue

            if not body_started:
                if element.name == "h2" and not subtitle_added and len(text) >= 40:
                    parts.append(text)
                    seen.add(text)
                    subtitle_added = True
                continue

            if element.name not in {"h2", "h3", "p", "li"}:
                continue

            parts.append(text)
            seen.add(text)
            max_text_chars = int(config.get("article_max_chars") or 12000) if isinstance(config, dict) else 12000
            if len(" ".join(parts)) >= max_text_chars:
                break

        return "\n\n".join(parts) if parts else None

    def normalize_text(self, value):
        return " ".join(str(value or "").replace("\xa0", " ").split())

    def is_metadata_text(self, text):
        lowered = text.lower()
        return (
            lowered in {
                "article",
                "share",
                "print",
                "more",
                "copy",
                "download ()",
                "linkedin",
                "twitter",
                "facebook",
                "or copy link",
            }
            or lowered.startswith("share ")
            or lowered.startswith("senior ")
            or lowered.startswith("united states")
            or lowered.endswith("@deloitte.com")
            or "min read" in lowered
        )

    def is_stop_text(self, text):
        lowered = text.lower()
        return lowered == "by" or lowered.startswith((
            "endnotes",
            "acknowledgments",
            "copyright",
            "related content",
            "deloitte insights and our research centers",
            "please enable javascript",
        ))
