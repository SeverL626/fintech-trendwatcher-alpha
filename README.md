# Fintech Trendwatcher

Сервис трендвотчера для финтех-публикаций: парсер собирает новости, модель OpenRouter превращает их в карточки сигналов, дедупликатор склеивает повторы, фронт показывает готовую витрину.

 ## Admin access + /update/status

- manager@redcat.tu
- rqbqerj1543tgjkq

> https://redcat-news.ru/update/status?token=rqbqerj1543tgjkq

## Быстрый Запуск

Локально через Docker:

```powershell
copy .env.example .env
# заполнить OPENROUTER_API_KEY в .env
docker compose up -d --build
```

Адреса:

```text
frontend: http://localhost:5173
backend:  http://localhost:5000
frontend-backend: http://localhost:5001
```

Vite dev server проксирует `/api` на `http://127.0.0.1:5001`, а `/update` и `/signals` на `http://127.0.0.1:5000`.

## API

Основные endpoints (`/api/*` обслуживает `frontend-backend`, update pipeline живет в `backend`):

```text
GET  /                     # настройки сервиса и update
GET  /signals              # карточки сигналов для backend/debug
GET  /update/status        # статус полного update
GET  /api/signals          # карточки для frontend
GET  /api/market           # MOEX-таблица для frontend
GET  /api/digests          # недельные дайджесты для frontend
POST /api/update           # запуск полного update из frontend
POST /api/admin/update     # совместимый endpoint кнопки обновления
```

Frontend также использует совместимые endpoints для demo-аккаунта, избранного и уведомлений (`/api/login`, `/api/me`, `/api/favorites`, `/api/notifications`). Реальные данные для витрины идут из `/api/signals` и `/api/market`.

## Update Pipeline

Полный цикл:

1. `parser` собирает новые публикации в `raw_news`.
2. `llm` берёт все `raw_news.status = 'new'` от старых к новым, нормализует текст и пишет в `signals`: `headline`, `summary`, `why_now`, `category`.
3. `embeddings` считает embedding по `headline + summary` и сохраняет его в `signals.embedding_json`.
4. `fintech_model` ставит `is_fintech`. Если `is_fintech = 0`, строка дальше не участвует в scoring/dedup и не попадает в витрину.
5. `feature_models` считают `scale_score`, `urgency_score`, `rigidity_score`.
6. `duplicates` склеивает fintech-дубли по embeddings, обновляет `sources`, `is_duplicate`, `duplicate_of`, `duplicate_group_id`.
7. `hotness` считается линейной моделью по `scale_score`, `urgency_score`, `rigidity_score`, числу дублей и авторитетности источников.
8. `weekly_digest` каждый понедельник в 00:00 MSK после update берёт топ-15 fintech-сигналов прошлой недели без дублей и пишет недельную сводку в `weekly_digests`.
9. При успехе `raw_news.status = 'processed'`; при ошибке `error`, чтобы строку можно было модерировать.

Особые правила дедупликации:

- Дедупликация работает только по `is_fintech = 1`.
- Сухие отчёты и таблицы не сравниваются.
- Дубли ищутся по всей базе, но склеиваются только пары публикаций с разницей дат до 3 дней.
- Для `Курсы валют` главным дублем выбирается самая свежая карточка, чтобы показывать актуальный курс.

Расписание:

```text
00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 Europe/Moscow
```

Одновременно может работать только один update. Ручной запуск доступен через 1 час после предыдущего старта любого update. Автозапуск по расписанию пропускается только если update уже идёт. Ограничения на длительность нет; час используется только для проверки устаревшего lock-файла.

Недельный дайджест создаётся в автоматический запуск понедельника 00:00 MSK. Если `weekly_digests` пустая, первый запуск работает в backfill-режиме и создаёт отчёты за все завершённые недели, где есть подходящие fintech-сигналы. После этого создаётся только последняя завершённая неделя. Если за неделю нет подходящих сигналов, stage пропускает её без записи.

## Database

SQLite:

```text
local:  data/app.db
server: /opt/myapp/data/app.db
```

### `sources`

Список источников для parser.

| Поле | Описание |
| --- | --- |
| `id` | ID источника |
| `name` | Название источника |
| `url` | URL источника |
| `source_type` | `rss`, `site`, `api`, `telegram` |
| `is_active` | Активен ли источник |
| `parse_frequency_minutes` | Частота проверки |
| `parser_config` | JSON с коннектором и настройками парсинга |
| `authority_score`, `authority_tier` | Авторитетность источника для выбора главной карточки дубля и итогового hotness |
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
| `content_hash` | Хеш текста/заголовка |
| `raw_data` | JSON с данными коннектора |
| `error_message` | Ошибка обработки моделью |

### `signals`

Готовые карточки после model.

| Поле | Описание |
| --- | --- |
| `id` | ID сигнала |
| `headline` | Короткий заголовок |
| `summary` | Нормализованная краткая выжимка новости |
| `embedding_json` | Embedding и метаданные embedding-модели |
| `processing_status` | Этап пайплайна: `llm_done`, `embedding_done`, `models_done`, `dedup_done`, `duplicate`, `error` |
| `is_fintech` | Флаг fintech/no модели; `0` дальше не участвует в scoring/dedup |
| `scale_score`, `urgency_score`, `rigidity_score` | Компоненты hotness-модели |
| `hotness` | Итоговая оценка линейной модели 0-5; `-1`, если оценка ещё не рассчитана |
| `why_now` | Актуальность события для банка |
| `category` | Одна из фиксированных категорий |
| `sources` | ID исходной публикации из `raw_news.id`; после дедупликации может быть списком через запятую |
| `is_duplicate` | Флаг вторичного дубля |
| `duplicate_of`, `duplicate_group_id` | Связь с главным сигналом дубля |
| `draft` | Пустое текстовое поле для ручного/служебного комментария |

Категории:

```text
Регулирование и комплаенс
Платежи и инфраструктура
Антифрод и кибербезопасность
Банковские продукты и клиентский опыт
Конкуренты и банковский рынок
Финтех и новые технологии
Идентификация и биометрия
Санкции и ограничения
Макроэкономика и ставки
Рынки и инвестиции
Финансовые результаты и отчетность
Статистика и данные
```

### `moex_daily_stats`

Дневная агрегированная статистика MOEX.

| Поле | Описание |
| --- | --- |
| `source_id` | Ссылка на `sources.id` |
| `trade_date` | Дата торгов |
| `securities_count`, `traded_securities_count` | Количество инструментов |
| `total_value`, `total_value_usd`, `total_volume`, `total_trades` | Обороты, объёмы, сделки |
| `average_last`, `average_marketprice` | Средние цены |
| `top_*` | Лидеры по обороту, объёму и сделкам |
| `moex_systime`, `raw_data`, `fetched_at` | Служебные данные |

### `weekly_digests`

Недельные отчёты для страницы «Дайджесты».

| Поле | Описание |
| --- | --- |
| `id` | ID дайджеста |
| `week_start`, `week_end` | Неделя отчёта |
| `title` | Короткий заголовок отчёта |
| `summary` | Главный вывод недели |
| `report` | Структурированный текст дайджеста |
| `moex_summary` | Не используется в текущей версии дайджеста |
| `news_ids` | JSON-массив ID сигналов, попавших в топ-15 |
| `model`, `prompt_version` | Модель и версия промта |
| `created_at`, `updated_at` | Служебные даты |

### Runtime Files

Лежат рядом с БД:

```text
parser.lock
update_last_start.json
update_status.json
parser_status.json
model_status.json
```

## Sources

Стартовый набор создаётся через `python back/init_db.py`.

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
| 39 | Deloitte Insights | `site` | `deloitte_insights` | `https://www.deloitte.com/us/en/insights.html` |
