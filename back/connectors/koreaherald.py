from .generic import HtmlConnector
from bs4 import BeautifulSoup


class KoreaheraldConnector(HtmlConnector):
    name = "koreaherald"

    def parse(self, source, config):
        config = {
            **config,
            "link_selector": "a[href*='/article/']",
            "url_contains": ["/article/"],
            "text_selector": "article p, .article_view p, #articleText p, main p",
            "require_date": True,
            "max_links": 30,
        }
        return super().parse(source, config)

    def parse_article_page(self, url, config, fallback_title=None, fallback_published_at=None):
        """Override to clean up Korea Herald specific junk."""
        response = self.fetch(url, config)
        soup = BeautifulSoup(response.text, "lxml")
        text_selectors = config.get("text_selectors") or config.get("text_selector")
        if isinstance(text_selectors, str):
            text_selectors = [text_selectors]
        
        return {
            "canonical_url": self.extract_canonical_url(soup, url),
            "title": self.extract_title(soup, fallback_title),
            "published_at": self.extract_published_at(soup) or fallback_published_at,
            "text": self.extract_koreaherald_text(soup, text_selectors),
        }

    def extract_koreaherald_text(self, soup, selectors=None):
        """Extract only article body text, skip title, date, and metadata."""
        selectors = selectors or ["article p", ".article_view p", "#articleText p", "main p"]
        
        parts = []
        seen = set()
        
        for selector in selectors:
            for element in soup.select(selector):
                text = element.get_text(" ", strip=True)
                if not text or text in seen:
                    continue
                
                # Skip metadata lines: "Published : ...", "Link copied!", etc
                text_lower = text.lower().strip()
                if any(marker in text_lower for marker in [
                    "published :",
                    "link copied",
                    "update :",
                    "written by",
                    "reporter :",
                    "email :",
                    "print article",
                    "send feedback",
                ]):
                    continue
                
                seen.add(text)
                parts.append(text)
            
            if len(" ".join(parts)) >= 300:
                break
        
        if parts:
            return "\n\n".join(parts)
        return None
