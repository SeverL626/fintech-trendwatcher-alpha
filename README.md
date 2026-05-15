# Fintech Trendwatcher


АККАУНТЫ И ПРОМОКОДЫ ДЛЯ ДОСТУПА
Promo codes: REDCAT2026, TRENDWOTCHER, FINTECHCAT

admin@redcat.local
Admin12345!

Сервис трендвотчера для финтех-публикаций: парсер собирает новости, модель OpenRouter превращает их в карточки сигналов, дедупликатор склеивает повторы, фронт показывает готовую витрину.

## Архитектура

```text
domain -> VPS nginx -> frontend container -> frontend-backend container -> backend container -> SQLite
```

- `frontend`: React/Vite, собирается в nginx-контейнер.
- `frontend-backend`: Flask API и auth layer из ветки `gemeni_api`; читает `data/app.db`, дергает update в `backend`.
- `backend`: Flask + Gunicorn, parser/model/duplicates/update pipeline.
- `data/app.db`: SQLite база и runtime JSON-статусы.
- `OPENROUTER_API_KEY`: ключ для модели и embeddings.

В production внешний домен должен вести на frontend. `backend` и `frontend-backend` публикуются только локально на VPS и доступны фронту через Docker network.

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

Без Docker для backend:

```powershell
pip install -r requirements.txt
python back\init_db.py
python back\app.py
```

Без Docker для frontend:

```powershell
cd front\my-app
npm install
npm run dev
```

Vite dev server проксирует `/api` на `http://127.0.0.1:5001`, а `/update` и `/signals` на `http://127.0.0.1:5000`.

## Environment

`.env.example` содержит публичный шаблон. Реальный `.env` не коммитить.

```env
COMPOSE_PROJECT_NAME=alfa-hackiton

BACKEND_CONTAINER_NAME=alfa-hackiton-backend-prod
BACKEND_PORT=5000
FRONT_BACKEND_CONTAINER_NAME=alfa-hackiton-frontend-backend-prod
FRONT_BACKEND_PORT=5001
FRONTEND_CONTAINER_NAME=alfa-hackiton-frontend-prod
FRONTEND_PORT=5173
JWT_SECRET_KEY=

DB_PATH=/app/data/app.db
OPENROUTER_API_KEY=sk-or-v1-...

# Только для тестов
UPDATE_PARSER_ONLY=0
PARSER_ONLY_SOURCE_IDS=
```

## API

Основные endpoints (`/api/*` обслуживает `frontend-backend`, update pipeline живет в `backend`):

```text
GET  /                     # настройки сервиса и update
GET  /signals              # карточки сигналов для backend/debug
GET  /update/status        # статус полного update
GET  /api/signals          # карточки для frontend
GET  /api/market           # MOEX-таблица для frontend
POST /api/update           # запуск полного update из frontend
POST /api/admin/update     # совместимый endpoint кнопки обновления
```

Frontend также использует совместимые endpoints для demo-аккаунта, избранного и уведомлений (`/api/login`, `/api/me`, `/api/favorites`, `/api/notifications`). Они нужны, чтобы UI не падал; реальные данные для витрины идут из `/api/signals` и `/api/market`.

## Update Pipeline

Полный цикл:

1. `parser` собирает новые публикации в `raw_news`.
2. `model` берёт все `raw_news.status = 'new'` от старых к новым, ставит строку в `processing`, вызывает OpenRouter и пишет карточку в `signals`.
3. При успехе `raw_news.status = 'processed'`; при ошибке `error`, чтобы строку можно было модерировать.
4. `duplicates` проверяет релевантные сигналы за последнюю неделю, добивает отсутствующие embeddings, применяет PCA-чистку и склеивает дубли.
5. В первой карточке дубля `signals.sources` становится списком `raw_news.id`; вторичные карточки получают `draft = "DUBLICATE OF <raw_news.id>"` и скрываются из выдачи.

Особые правила дедупликации:

- `hotness=1`, сухие отчёты и таблицы не сравниваются.
- Дубли ищутся только в окне последней недели.
- Для `Курсы валют` главным дублем выбирается самая свежая карточка, чтобы показывать актуальный курс.

Расписание:

```text
00:00, 03:00, 06:00, 09:00, 12:00, 15:00, 18:00, 21:00 Europe/Moscow
```

Одновременно может работать только один update. Ручной запуск доступен через 1 час после предыдущего старта любого update. Автозапуск по расписанию пропускается только если update уже идёт. Ограничения на длительность нет; час используется только для проверки устаревшего lock-файла.

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
| `hotness` | Важность 1-5 |
| `why_now` | Банковский смысл события сейчас |
| `category` | Одна из фиксированных категорий |
| `sources` | ID исходной публикации из `raw_news.id`; после дедупликации может быть списком через запятую |
| `summary` | Краткая выжимка; пусто для `hotness=1` |
| `draft` | Пусто по умолчанию; embedding JSON или `DUBLICATE OF <raw_news.id>` после дедупликации |

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
| `top_*` | Инструменты-лидеры по обороту, объёму и сделкам |
| `moex_systime`, `raw_data`, `fetched_at` | Служебные данные |

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

## Frontend

React/Vite приложение лежит в `front/my-app`.

Страницы:

```text
Home
Cards / All news
Search
MOEX
Account
Notifications
Register
Login
Admin users/promos
```

Фронт работает через backend из `front/my-app/backend`. Он хранит пользователей, избранное и уведомления в `data/redcat.db`, а сигналы и MOEX читает из основной `data/app.db`.

## Production Deploy

На VPS:

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
mkdir -p data
nano .env
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker compose -f docker-compose.prod.yml logs -f backend
```

Не удалять `/opt/myapp/data` и не запускать `docker compose down -v`, иначе можно потерять БД.

## Домен -> VPS -> Frontend

Сейчас должно стать так:

```text
domain -> VPS nginx:80/443 -> frontend container:80 -> frontend-backend:5001 -> backend:5000
```

Backend в `docker-compose.prod.yml` уже слушает только локально:

```yaml
ports:
  - "127.0.0.1:${BACKEND_PORT:-5000}:5000"
```

Frontend наружу:

```yaml
ports:
  - "${FRONTEND_PORT:-5173}:80"
```

Frontend-backend тоже локальный:

```yaml
ports:
  - "127.0.0.1:${FRONT_BACKEND_PORT:-5001}:5001"
```

### 1. DNS

У регистратора домена:

```text
A     @      <VPS_IP>
A     www    <VPS_IP>
```

Подождать обновления DNS.

### 2. `.env` на сервере

Для production удобно оставить backend локальным, а frontend открыть на localhost-порту для внешнего nginx:

```env
BACKEND_PORT=5000
FRONT_BACKEND_PORT=5001
FRONTEND_PORT=5173
OPENROUTER_API_KEY=sk-or-v1-...
JWT_SECRET_KEY=<long-random-string>
```

### 3. Nginx на VPS

Пример `/etc/nginx/sites-available/fintech-trendwatcher`:

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Включить сайт:

```bash
sudo ln -s /etc/nginx/sites-available/fintech-trendwatcher /etc/nginx/sites-enabled/fintech-trendwatcher
sudo nginx -t
sudo systemctl reload nginx
```

### 4. HTTPS

```bash
sudo certbot --nginx -d example.com -d www.example.com
sudo systemctl reload nginx
```

### 5. Проверка

```bash
curl -I http://127.0.0.1:5173
curl http://127.0.0.1:5001/api/health
curl http://127.0.0.1:5000/update/status
curl https://example.com/api/signals?limit=1
```

Ожидаемо:

- домен открывает фронт;
- `/api/*` с домена проксируется фронтовым nginx-контейнером в `frontend-backend`;
- `frontend-backend` читает `data/app.db` и запускает `/update` в `backend`;
- прямые backend-порты наружу не нужны.
