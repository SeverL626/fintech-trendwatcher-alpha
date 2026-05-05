from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .base import BaseConnector


class TelegramConnector(BaseConnector):
    name = "telegram"

    def parse(self, source, config):
        channel = config.get("channel") or self.channel_from_url(source["url"])
        if not channel:
            raise ValueError(f"Telegram channel is not configured for source {source['name']}")

        response = self.fetch(f"https://t.me/s/{channel}", config)
        soup = BeautifulSoup(response.text, "lxml")
        items = []
        max_links = int(config.get("max_links") or 30)

        for message in soup.select(".tgme_widget_message"):
            post_id = message.get("data-post")
            if not post_id:
                continue

            url = f"https://t.me/{post_id}"
            published_at = self.extract_message_date(message)
            if not self.is_recent(published_at, config):
                continue

            text = self.extract_message_text(message)
            if not text:
                continue

            title = self.make_title(text, source["name"])
            items.append(self.make_news_item(url, title, published_at, text, {
                "adapter": self.name,
                "source": source["name"],
                "source_url": source["url"],
                "channel": channel,
                "post_id": post_id,
                "source_reliability": config.get("source_reliability"),
            }))
            if len(items) >= max_links:
                break

        return items

    def channel_from_url(self, url):
        path = urlsplit(url).path.strip("/")
        if not path:
            return None
        if path.startswith("s/"):
            path = path[2:]
        return path.split("/", 1)[0]

    def extract_message_date(self, message):
        time_element = message.select_one("time[datetime]")
        if not time_element:
            return None
        return self.normalize_published_at(time_element.get("datetime"))

    def extract_message_text(self, message):
        text_element = message.select_one(".tgme_widget_message_text")
        if not text_element:
            return ""
        for hidden in text_element.select(".tgme_widget_message_text .emoji"):
            hidden.decompose()
        return self.html_to_text(str(text_element))

    def make_title(self, text, fallback):
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if not first_line:
            return fallback
        if len(first_line) <= 140:
            return first_line
        return f"{first_line[:137].rstrip()}..."
