# Fintech Trendwatcher

Backend-сервис для сбора открытых финтех-публикаций и формирования карточек сигналов для банка.

## API

```text
GET /                 # настройки сервиса и update
GET /update           # полный цикл: parser -> model
GET /update/status    # статус полного цикла и этапов
GET /signals          # готовые карточки сигналов
```

## Update

Цикл:

1. `parser` собирает новые публикации в `raw_news`.
2. `model` берёт все `raw_news.status = 'new'` от старых к новым и пишет карточки в `signals`.

Автозапуск:

```text
00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 Europe/Moscow
```

Тайм-аут статуса: 1 час. Одновременно может работать только один update. Если update уже идёт, ручной или автоматический запуск не стартует второй процесс.

## Sources

Стартовый набор источников создаётся через `python back/init_db.py`.

| ID | Источник | Тип | Коннектор | URL |
|---:|---|---|---|---|
| 2 | Минфин России: пресс-центр | `site` | `minfin` | `https://minfin.gov.ru/ru/press-center/` |
| 3 | Росстат: национальные счета | `site` | `rosstat` | `https://rosstat.gov.ru/statistics/accounts` |
| 4 | MOEX ISS shares | `api` | `moex` | `https://iss.moex.com/iss/engines/stock/markets/shares/securities.json` |
| 5 | Альфа-Банк: новости | `site` | `alfabank` | `https://alfabank.ru/news/t/` |
| 6 | Сбер: пресс-релизы | `site` | `sber` | `https://www.sberbank.com/ru/news-and-media/press-releases` |
| 7 | Т-Банк: новости | `site` | `tbank` | `https://www.tbank.ru/about/news/` |
| 8 | ВТБ: пресс-центр и IR | `site` | `vtb` | `https://www.vtb.ru/about/press/` |
| 9 | РБК RSS | `rss` | `rbc` | `https://rssexport.rbc.ru/rbcnews/news/30/full.rss` |
| 10 | Ведомости RSS: банки | `rss` | `vedomosti` | `https://www.vedomosti.ru/rss/rubric/finance/banks` |
| 11 | Коммерсантъ: финансы | `site` | `kommersant` | `https://www.kommersant.ru/finance` |
| 12 | Telegram: Банк России | `telegram` | `telegram` | `https://t.me/centralbank_russia` |
| 13 | Telegram: Минфин России | `telegram` | `telegram` | `https://t.me/minfin` |
| 14 | Telegram: Frank Media | `telegram` | `telegram` | `https://t.me/frank_media` |
| 15 | Telegram: РБК | `telegram` | `telegram` | `https://t.me/rbc_news` |
| 16 | Telegram: Ведомости | `telegram` | `telegram` | `https://t.me/vedomosti` |
| 17 | Telegram: Коммерсантъ | `telegram` | `telegram` | `https://t.me/kommersant` |
| 18 | Telegram: Интерфакс | `telegram` | `telegram` | `https://t.me/interfaxonline` |
| 19 | Telegram: Банкста | `telegram` | `telegram` | `https://t.me/banksta` |
| 20 | Telegram: MMI | `telegram` | `telegram` | `https://t.me/russianmacro` |
| 21 | Telegram: MarketTwits | `telegram` | `telegram` | `https://t.me/markettwits` |
| 22 | Telegram: РДВ | `telegram` | `telegram` | `https://t.me/AK47pfl` |
| 23 | Telegram: Финсайд | `telegram` | `telegram` | `https://t.me/finside` |
| 24 | Росфинмониторинг: информационные сообщения | `site` | `fedsfm` | `https://fedsfm.ru/` |
| 25 | ФНС России: новости | `site` | `nalog` | `https://www.nalog.gov.ru/rn77/news/activities_fts/` |
| 26 | Банк России: новости | `api` | `cbr_news` | `https://cbr.ru/news/` |
| 27 | Ассоциация ФинТех: пресс-центр | `site` | `html` | `https://www.fintechru.org/press-center/` |
| 28 | Fintech News Singapore RSS | `rss` | `rss` | `https://fintechnews.sg/feed/` |
| 29 | The Paypers: fintech and payments | `site` | `html` | `https://thepaypers.com/` |
| 30 | IBS Intelligence RSS | `rss` | `rss` | `https://ibsintelligence.com/feed/` |
| 31 | TechAfrica News RSS | `rss` | `rss` | `https://techafricanews.com/feed/` |
| 32 | Biometric Update RSS | `rss` | `rss` | `https://www.biometricupdate.com/feed` |
| 33 | Cloud Computing News RSS | `rss` | `rss` | `https://www.cloudcomputing-news.net/feed/` |
| 34 | GlobeNewswire: public companies | `rss` | `rss` | `https://www.globenewswire.com/RssFeed/orgclass/1/feedTitle/GlobeNewswire%20-%20News%20about%20Public%20Companies` |
| 35 | ECB: press releases RSS | `rss` | `rss` | `https://www.ecb.europa.eu/rss/press.html` |
| 36 | Korea Herald: business | `site` | `koreaherald` | `https://www.koreaherald.com/business` |
| 37 | The Fintech Times RSS | `rss` | `rss` | `https://thefintechtimes.com/feed/` |

## Database

SQLite DB: `data/app.db` локально, `/opt/myapp/data/app.db` на сервере.

### `sources`

Список источников для parser.

| Поле | Описание |
| --- | --- |
| `id` | ID источника |
| `name` | Название источника |
| `url` | URL источника |
| `source_type` | `rss`, `site`, `api`, `telegram` |
| `is_active` | Используется ли источник |
| `parse_frequency_minutes` | Частота проверки |
| `parser_config` | JSON с коннектором и настройками парсинга |
| `last_parsed_at` | Последняя проверка |
| `created_at`, `updated_at` | Служебные даты |

### `raw_news`

Сырые публикации, найденные parser.

| Поле | Описание |
| --- | --- |
| `id` | ID публикации |
| `source_id` | Ссылка на `sources.id` |
| `url` | URL публикации, уникальный |
| `title` | Заголовок |
| `text` | Сырой текст |
| `published_at` | Дата публикации |
| `parsed_at` | Когда parser нашёл запись |
| `status` | `new`, `processing`, `processed`, `skipped`, `error` |
| `content_hash` | Хеш текста/заголовка для дублей |
| `raw_data` | JSON с дополнительными данными коннектора |
| `error_message` | Ошибка обработки моделью |

`model` берёт только строки со статусом `new`. При успехе ставит `processed`, при ошибке `error`.

### `signals`

Готовые карточки после model.

| Поле | Описание |
| --- | --- |
| `id` | ID сигнала |
| `headline` | Короткий заголовок |
| `hotness` | Важность 1-5 |
| `why_now` | Почему важно сейчас; для мусора `--`, для сухих отчётов `Отчёт` |
| `category` | `Инвестиции и рынки`, `Корпоративные финансы и сделки`, `Финансовые результаты`, `Макроэкономика и статистика` |
| `sources` | ID исходной публикации из `raw_news.id` |
| `summary` | Короткая выжимка; пусто для `hotness=1` |
| `draft` | Пусто по умолчанию; только ошибки/сомнения/ограничения |

### `moex_daily_stats`

Дневная агрегированная статистика MOEX.

| Поле | Описание |
| --- | --- |
| `source_id` | Ссылка на `sources.id` |
| `trade_date` | Дата торгов |
| `securities_count`, `traded_securities_count` | Количество инструментов |
| `total_value`, `total_value_usd`, `total_volume`, `total_trades` | Обороты/объёмы/сделки |
| `average_last`, `average_marketprice` | Средние цены |
| `top_*` | Инструменты-лидеры по обороту, объёму и сделкам |
| `moex_systime`, `raw_data`, `fetched_at` | Служебные данные |

### Runtime Files

Лежат рядом с БД и не коммитятся:

```text
parser.lock
parser_manual_throttle.json
update_status.json
```

## Environment

```env
DB_PATH=/app/data/app.db
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_TIMEOUT_SECONDS=60
OPENROUTER_MAX_RETRIES=3
OPENROUTER_RETRY_SECONDS=20
OPENROUTER_REQUEST_DELAY_SECONDS=0
```

## Local Run

```powershell
python back\init_db.py
python back\app.py
```

Docker:

```powershell
docker compose up -d --build
docker compose logs -f backend
```

## Production

Production compose exposes backend only on localhost:

```text
127.0.0.1:${BACKEND_PORT}:5000
```

Runtime data is mounted to `/app/data`; production DB path:

```text
/opt/myapp/data/app.db
```

Deploy:

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
mkdir -p data
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f
```

Do not remove `/opt/myapp/data` and do not run `docker compose down -v`.

## Nginx

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
