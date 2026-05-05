from __future__ import annotations

import json
from datetime import datetime

try:
    from back.connectors.telegram import TelegramConnector
except ModuleNotFoundError:
    from connectors.telegram import TelegramConnector


DEFAULT_TELEGRAM_CONFIG = {
    "connector": "telegram",
    "max_age_hours": 1,
    "strict_dates": True,
    "max_future_hours": 2,
    "min_text_length": 5,
    "timeout": 15,
}


def parse_channel(channel: str, name: str | None = None, hours: int = 1):
    source = {
        "name": name or f"Telegram: {channel}",
        "url": f"https://t.me/{channel}",
    }
    config = {
        **DEFAULT_TELEGRAM_CONFIG,
        "channel": channel,
        "max_age_hours": hours,
    }
    return TelegramConnector().parse(source, config)


def main():
    channel = "centralbank_russia"
    items = parse_channel(channel)
    print(json.dumps({
        "channel": channel,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "items": items,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
