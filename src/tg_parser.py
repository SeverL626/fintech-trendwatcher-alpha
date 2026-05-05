import asyncio
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from gemeni_api_test import NewsAnalyzer
from google.genai.errors import ServerError  # импорт нужного исключения

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


async def analyze_with_retry(analyzer: NewsAnalyzer, max_retries: int = 3, base_delay: float = 1.0):
    last_exception = None
    for attempt in range(max_retries):
        try:
            return await analyzer.analyze()
        except ServerError as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"Повторная попытка {attempt+1} для сообщения: {e}. Ожидание {delay:.1f}с...")
                await asyncio.sleep(delay)
            else:
                print(f"Исчерпаны попытки для сообщения: {e}")
    raise last_exception


async def main():
    parser = TelegramChannelParser(
        channel_username="fcs_hse",
        days_limit=3
    )

    messages = await parser.parse()
    tasks = []

    for msg in messages:
        if msg['text'] != '':
            analyzer = NewsAnalyzer(
                text=msg['text'],
                date=msg['date'],
                title=None
            )
            tasks.append(analyze_with_retry(analyzer))

    results = await asyncio.gather(*tasks)
    for result in results:
        print(result)
        print()
        print()


if __name__ == "__main__":
    asyncio.run(main())