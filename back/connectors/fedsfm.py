from .generic import HtmlConnector
from bs4 import BeautifulSoup
import re


class FedsfmConnector(HtmlConnector):
    name = "fedsfm"

    def parse(self, source, config):
        config = {
            **config,
            "link_selector": "a[href^='/news/']",
            "url_contains": ["/news/"],
            "text_selector": "p",
            "require_date": True,
            "prefer_listing_title": True,
            "max_links": 30,
        }
        return super().parse(source, config)

    def parse_article_page(self, url, config, fallback_title=None, fallback_published_at=None):
        """Override to clean up fedsfm.ru specific format."""
        response = self.fetch(url, config)
        soup = BeautifulSoup(response.text, "lxml")
        text_selectors = config.get("text_selectors") or config.get("text_selector")
        if isinstance(text_selectors, str):
            text_selectors = [text_selectors]
        
        return {
            "canonical_url": self.extract_canonical_url(soup, url),
            "title": self.extract_title(soup, fallback_title),
            "published_at": self.extract_published_at(soup) or fallback_published_at,
            "text": self.extract_fedsfm_text(soup, text_selectors),
        }

    def extract_fedsfm_text(self, soup, selectors=None):
        """Extract article text and remove 'Дата публикации' line."""
        selectors = selectors or ["p"]
        
        parts = []
        seen = set()
        
        for selector in selectors:
            for element in soup.select(selector):
                text = element.get_text(" ", strip=True)
                if not text or text in seen:
                    continue
                
                # Skip "Дата публикации:" lines (e.g., "Дата публикации: 05.05.2026 17:00")
                if re.match(r"Дата публикации:\s*\d{2}\.\d{2}\.\d{4}", text):
                    continue
                
                seen.add(text)
                parts.append(text)
            
            if len(" ".join(parts)) >= 500:
                break
        
        if parts:
            return "\n\n".join(parts)
        return None
