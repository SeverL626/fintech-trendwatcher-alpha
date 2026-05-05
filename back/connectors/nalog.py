from .generic import HtmlConnector
from bs4 import BeautifulSoup


class NalogConnector(HtmlConnector):
    name = "nalog"

    def parse(self, source, config):
        config = {
            **config,
            "link_selector": "a[href*='/news/activities_fts/']",
            "url_contains": ["/news/activities_fts/"],
            "text_selector": ".content p, main p, p",
            "require_date": True,
            "max_links": 40,
        }
        return super().parse(source, config)

    def parse_article_page(self, url, config, fallback_title=None, fallback_published_at=None):
        """Override to clean up nalog.gov.ru specific junk."""
        response = self.fetch(url, config)
        soup = BeautifulSoup(response.text, "lxml")
        text_selectors = config.get("text_selectors") or config.get("text_selector")
        if isinstance(text_selectors, str):
            text_selectors = [text_selectors]
        
        return {
            "canonical_url": self.extract_canonical_url(soup, url),
            "title": self.extract_title(soup, fallback_title),
            "published_at": self.extract_published_at(soup) or fallback_published_at,
            "text": self.extract_nalog_text(soup, text_selectors),
        }

    def extract_nalog_text(self, soup, selectors=None):
        """Extract article text and remove nalog.gov.ru specific junk."""
        selectors = selectors or [".content p", "main p", "p"]
        
        parts = []
        seen = set()
        
        # Common junk markers to skip
        skip_markers = {
            "это архивная публикация",
            "сообщение успешно отправлено",
            "© 2005",
            "фнс россии",
            "все права защищены",
        }
        
        for selector in selectors:
            for element in soup.select(selector):
                text = element.get_text(" ", strip=True)
                if not text or text in seen:
                    continue
                
                # Skip if text contains junk markers
                text_lower = text.lower()
                if any(marker in text_lower for marker in skip_markers):
                    continue
                
                seen.add(text)
                parts.append(text)
            
            if len(" ".join(parts)) >= 500:
                break
        
        if parts:
            return "\n\n".join(parts)
        return None
