from .generic import RssConnector
from bs4 import BeautifulSoup


class MinfinConnector(RssConnector):
    name = "minfin"

    def parse(self, source, config):
        rss_source = dict(source)
        rss_source["url"] = "https://minfin.gov.ru/rss_news?mod=news&lim=50"
        config = {
            **config,
            "text_selectors": [
                "article p",
                ".news-detail p",
                ".content p",
                "main p",
            ],
            "fetch_article_text": True,
        }
        return super().parse(rss_source, config)

    def fetch_article(self, url, title, published_at, config):
        try:
            response = self.fetch(url, config)
            soup = BeautifulSoup(response.text, "lxml")
            page_title = self.extract_title(soup, title)
            page_date = self.extract_published_at(soup) or published_at
            return {
                "canonical_url": self.extract_canonical_url(soup, url),
                "title": page_title,
                "published_at": page_date,
                "text": self.extract_minfin_text(soup, title),
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

    def extract_minfin_text(self, soup, title):
        lines = [
            line.strip()
            for line in soup.get_text("\n", strip=True).splitlines()
            if line.strip()
        ]
        start = 0
        if title:
            for index, line in enumerate(lines):
                if line == title:
                    start = index + 1
                    break
        if start == 0:
            for index, line in enumerate(lines):
                if any(char.isdigit() for char in line) and self.normalize_published_at(line):
                    start = index + 1
                    break

        while start < len(lines) and (
            self.normalize_published_at(lines[start])
            or lines[start] in {"Пресс-центр", "Новости"}
        ):
            start += 1

        stop_markers = {
            "Новости по теме",
            "Все Новости",
            "Поделиться",
            "Распечатать",
        }
        parts = []
        for line in lines[start:]:
            if line in stop_markers:
                break
            if line.lower() in {"новости", "шкиб", "инициативное бюджетирование"}:
                break
            parts.append(line)

        return "\n".join(parts).strip() or None
