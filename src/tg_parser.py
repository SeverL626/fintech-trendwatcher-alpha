import asyncio
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient


API_ID = 36885579
API_HASH = "9c60a959c58666edf16c9237bdfb61aa"


class TelegramChannelParser:
    def __init__(self, channel_username, days_limit):
        self.channel_username = channel_username
        self.days_limit = days_limit
        self.client = TelegramClient("session", API_ID, API_HASH)

    async def parse(self):
        await self.client.start()

        entity = await self.client.get_entity(self.channel_username)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=self.days_limit)

        results = []

        async for message in self.client.iter_messages(entity, limit=None):
            if message.date < cutoff_date:
                break

            results.append({
                "date": message.date.isoformat(),
                "text": message.message,
            })

        return results


async def main():
    parser = TelegramChannelParser(
        channel_username="exploitex",
        days_limit=3
    )

    messages = await parser.parse()

    for msg in messages:
        print(msg)


if __name__ == "__main__":
    asyncio.run(main())