from bs4 import BeautifulSoup

from .base import BaseConnector


class RbcConnector(BaseConnector):
    name = "rbc"

    def parse(self, source, config):
        candidates = self.collect_rss_candidates(source, config)
        items = []
        seen_urls = set()

        for candidate in candidates:
            article_url = candidate["url"]
            if article_url in seen_urls:
                continue
            seen_urls.add(article_url)

            article = self.fetch_article(article_url, config)
            title = article.get("title") or candidate.get("title") or source["name"]
            published_at = (
                article.get("published_at")
                or candidate.get("published_at")
            )
            if not self.is_recent(published_at, config):
                continue

            article_text = article.get("text")
            rss_description = candidate.get("rss_description") or ""
            use_article_text = bool(article_text and len(article_text) > len(rss_description))
            text = article_text if use_article_text else rss_description
            items.append(self.make_news_item(
                article.get("canonical_url") or article_url,
                title,
                published_at,
                text,
                {
                    "adapter": self.name,
                    "source": source["name"],
                    "source_url": source["url"],
                    "rss_description": rss_description,
                    "text_source": "article_html" if use_article_text else "rss_description_fallback",
                    "article_error": article.get("error"),
                    "discovery_source": "rss",
                },
            ))

        return items

    def collect_rss_candidates(self, source, config):
        response = self.fetch(source["url"], config)
        root = self.parse_xml(response.content)
        candidates = []

        for element in root.iter():
            if self.local_name(element.tag) != "item":
                continue

            title = self.child_text(element, ["title"]) or source["name"]
            article_url = self.child_text(element, ["link", "guid"]) or source["url"]
            published_at = self.normalize_published_at(
                self.child_text(element, ["pubDate", "dc:date", "date"])
            )
            rss_description = self.html_to_text(
                self.child_text(element, ["description", "content:encoded", "summary"])
                or title
            )
            candidates.append({
                "url": article_url,
                "title": title,
                "published_at": published_at,
                "rss_description": rss_description,
                "discovery_source": "rss",
            })

        return candidates

    def fetch_article(self, article_url, config):
        if not config.get("fetch_article_text", True):
            return {
                "canonical_url": article_url,
                "title": None,
                "published_at": None,
                "text": None,
                "error": None,
            }

        try:
            response = self.fetch(article_url, config)
        except Exception as error:
            return {
                "canonical_url": article_url,
                "title": None,
                "published_at": None,
                "text": None,
                "error": str(error),
            }

        soup = BeautifulSoup(response.text, "lxml")
        return {
            "canonical_url": self.extract_canonical_url(soup) or article_url,
            "title": self.extract_title(soup),
            "published_at": self.extract_published_at(soup),
            "text": self.extract_article_text(soup),
            "error": None,
        }

    def extract_article_text(self, soup):
        selectors = [
            ".article__text p",
            ".article__text__overview",
            ".article__body p",
            "article p",
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
        if meta_description:
            return meta_description.get("content")

        return None

    def extract_title(self, soup):
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
        return None

    def extract_published_at(self, soup):
        selectors = [
            "meta[property='article:published_time']",
            "time[datetime]",
            ".article__header__date",
            ".article__date",
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

    def extract_canonical_url(self, soup):
        canonical = soup.select_one("link[rel='canonical']")
        if canonical and canonical.get("href"):
            return canonical.get("href")
        og_url = soup.select_one("meta[property='og:url']")
        if og_url and og_url.get("content"):
            return og_url.get("content")
        return None
