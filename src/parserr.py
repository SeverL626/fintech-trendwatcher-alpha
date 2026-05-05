from google import genai
import requests
from bs4 import BeautifulSoup
import dateparser
from dateparser.search import search_dates
from datetime import datetime, timedelta
import time
from urllib.parse import urljoin
from random import uniform


class NewsParser:
    def __init__(
        self,
        base_url,
        max_age_days=2,
        link_selector="a.g-inline-text-badges.js-item-link",
        date_selectors=None,
        text_selector="article p",
        pause=0.5,
        timeout=15,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        use_fallback_date_search=True,
        date_formats=None
    ):
        self.base_url = base_url
        self.max_age_days = max_age_days
        self.link_selector = link_selector
        self.pause = pause
        self.timeout = timeout
        self.headers = {"User-Agent": user_agent}
        self.use_fallback_date_search = use_fallback_date_search
        self.date_formats = date_formats

        if isinstance(text_selector, str):
            self.text_selectors = [text_selector]
        else:
            self.text_selectors = text_selector

        if date_selectors is None:
            self.date_selectors = [
                "meta[property='article:published_time']",
                "meta[name='pubdate']",
                "time[datetime]",
                ".article__date",
                ".post__date",
                ".date"
            ]
        else:
            self.date_selectors = date_selectors

        self.age_limit = datetime.now() - timedelta(days=max_age_days)

    def _fetch_page(self, url, max_retries=3, backoff_factor=1.5):
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=self.headers, timeout=self.timeout)
                resp.raise_for_status()
                return BeautifulSoup(resp.text, "lxml")
            except requests.exceptions.HTTPError as e:
                print(f"HTTP ошибка при загрузке {url}: {e}. Попытка {attempt + 1}/{max_retries}")
                if e.response.status_code == 406:
                    wait_time = backoff_factor ** attempt + uniform(0, 1) * 5
                    print(f"Ожидаем {wait_time:.2f} сек. перед повтором...")
                    time.sleep(wait_time)
                else:
                    return None
            except Exception as e:
                print(f"Ошибка при загрузке {url}: {e}. Попытка {attempt + 1}/{max_retries}")
                time.sleep(backoff_factor ** attempt)
        print(f"Не удалось загрузить {url} после {max_retries} попыток.")
        return None

    def _extract_date(self, soup):
        for sel in self.date_selectors:
            elem = soup.select_one(sel)
            if not elem:
                continue

            if elem.name == "meta":
                date_str = elem.get("content")
            elif elem.name == "time":
                date_str = elem.get("datetime")
            else:
                date_str = elem.get_text(strip=True)

            if not date_str:
                continue

            date_str = date_str.replace("Обновлено", "").replace("Опубликовано", "").strip()
            parsed = dateparser.parse(
                date_str,
                languages=["ru", "en"],
                settings={"PREFER_DATES_FROM": "past"},
                date_formats=self.date_formats
            )
            if parsed:
                return parsed.replace(tzinfo=None)

        if self.use_fallback_date_search:
            text = soup.get_text()
            result = search_dates(
                text,
                languages=["ru", "en"],
                settings={"PREFER_DATES_FROM": "past"}
            )
            if result:
                return result[0][1].replace(tzinfo=None)

        return None

    def _extract_text(self, soup):
        all_elements = []
        for sel in self.text_selectors:
            elements = soup.select(sel)
            all_elements.extend(elements)

        if not all_elements:
            paragraphs = soup.find_all("p")
            all_elements.extend(paragraphs)

        unique_elements = []
        seen = set()
        for el in all_elements:
            if id(el) not in seen:
                unique_elements.append(el)
                seen.add(id(el))

        unique_elements.sort(key=lambda el: el.sourceline if el.sourceline is not None else 0)

        parts = []
        for el in unique_elements:
            text = el.get_text(strip=True)
            if text:
                parts.append(text)

        return "\n\n".join(parts)

    def _process_article(self, article_url, title):
        soup = self._fetch_page(article_url)
        if not soup:
            return None

        pub_date = self._extract_date(soup)
        if not pub_date:
            print(f"Не удалось определить дату: {article_url}. Пропускаем.")
            return None

        if pub_date < self.age_limit:
            print(f"Новость старше {self.max_age_days} дн.: {article_url}. Останавливаем парсинг.")
            return False

        full_text = self._extract_text(soup)
        return {
            "url": article_url,
            "title": title,
            "date": pub_date.strftime("%d-%m-%Y"),
            "text": full_text
        }

    def parse(self):
        news_list = []

        soup = self._fetch_page(self.base_url)
        if not soup:
            return news_list

        links = soup.select(self.link_selector)
        if not links:
            print("Ссылки не найдены. Проверьте селектор.")
            return news_list

        print(f"Найдено ссылок: {len(links)}")

        for link_tag in links:
            href = link_tag.get("href")
            if not href:
                continue

            article_url = urljoin(self.base_url, href)
            title = link_tag.get_text(strip=True)

            time.sleep(self.pause)

            result = self._process_article(article_url, title)
            if result is False:
                break
            elif result is not None:
                news_list.append(result)
                print(f"Собрана: {title[:80]}... | {result['date']}")

        return news_list


if __name__ == "__main__":
    parser = NewsParser(
        base_url="https://trends.rbc.ru/trends/tag/fintech",
        max_age_days=90,
        link_selector="a.g-inline-text-badges.js-item-link",
        date_selectors=[
            ".atricle__date-update",
            ".article__date-update",
            ".article__date",
            ".post__date",
            ".date",
            "time[datetime]",
            "meta[property='article:published_time']",
            "meta[name='pubdate']"
        ],
        text_selector=["article p", "article h1", "article h2", "article h3", "article h4", "article h5", "article h6"],
        pause=1.0,
        use_fallback_date_search=False
    )
    news = parser.parse()
    client = genai.Client(api_key='AIzaSyC2LX-ihqh_1eGD52BIRbLyzpiAne5syUE')

    print(f"\nСобрано {len(news)} новостей.")
    for i, item in enumerate(news, 1):
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=f"""
            Твоя задача — проанализировать новостной текст и сформировать аналитическую карточку для банка.

            Контекст:
            Ты работаешь как аналитик в банке (розничный/корпоративный бизнес, платежи, финтех).
            Важно оценивать влияние новости на:
            - доходы (комиссии, эквайринг, кредитование и т.д.)
            - клиентскую базу
            - конкурентную позицию
            - продуктовую стратегию
            - регуляторные риски

            Требования к ответу:
            - Пиши на русском языке.
            - Строго соблюдай структуру и названия полей.
            - Кратко, без воды, но с аналитической ценностью.
            - Не пересказывай текст — интерпретируй.
            - Если данных мало — делай обоснованные предположения.

            Формат ответа:

            Headline: <краткий заголовок, отражающий суть и игрока>

            Hotness: <оценка от 1 до 5>
            (1 — шум, 3 — значимо для сегмента, 5 — стратегическое влияние на рынок/банк)

            Why now: <почему это происходит сейчас: конкуренция, регуляторика, экономика, технологии>

            Category: <одна категория: платежи / эквайринг / кредитование / BNPL / финтех / регулирование / digital-банк и т.д.>

            Sources: <источники из текста: оригинал + перепечатки, если есть>

            Summary: <суть новости в 2–3 предложениях>

            Draft: <управленческая интерпретация для банка:
            - риск/возможность
            - на что влияет (доходы, клиенты, продукт)
            - 1–2 конкретных действия (проанализировать, запустить пилот, изменить тариф и т.д.)>

            ---

            Новостной текст:
            {item["text"]}
            """
        )
        print(response.text)