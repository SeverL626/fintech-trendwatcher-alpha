# Fintech Trendwatcher

Сервис для сбора новостей, документов и рыночной статистики по финтех/экономической повестке.

## Запуск

Локально без Docker:

```powershell
python back\init_db.py     # обнуление базы данных (необязательно)
python back\app.py         # старт программы
```

IP:

```text
http://127.0.0.1:5000
```

Через Docker:

```powershell
docker compose up -d --build
```

## Парсинг

Запустить все активные источники:

```text
http://127.0.0.1:5000/parser
```

Окно поиска по умолчанию: последние 1 сутки. Фильтрации по содержанию сейчас нет: парсер собирает данные из подключенных источников, релевантность будет отдельным слоем.

Новости и документы пишутся в `raw_news`. Дневная статистика MOEX из ISS API пишется отдельно в `moex_daily_stats`.

## Источники

| ID | Источник | URL | Тип | Коннектор | Статус | Куда пишется |
|---:|---|---|---|---|---|---|
| 1 | Банк России: новости, интервью, выступления | `https://www.cbr.ru/rss/eventrss` | `rss` | `cbr` | активен | `raw_news` |
| 2 | Минфин России: пресс-центр | `https://minfin.gov.ru/ru/press-center/` | `site` | `minfin` | активен | `raw_news` |
| 3 | Росстат: национальные счета | `https://rosstat.gov.ru/statistics/accounts` | `site` | `rosstat` | активен, `verify_ssl=false` | `raw_news` |
| 4 | MOEX ISS shares | `https://iss.moex.com/iss/engines/stock/markets/shares/securities.json` | `api` | `moex` | активен | `moex_daily_stats` |
| 5 | Альфа-Банк: новости | `https://alfabank.ru/news/t/` | `site` | `alfabank` | активен | `raw_news` |
| 6 | Сбер: пресс-релизы | `https://www.sberbank.com/ru/news-and-media/press-releases` | `site` | `sber` | активен | `raw_news` |
| 7 | Т-Банк: новости | `https://www.tbank.ru/about/news/` | `site` | `tbank` | активен | `raw_news` |
| 8 | ВТБ: пресс-центр и IR | `https://www.vtb.ru/about/press/` | `site` | `vtb` | активен | `raw_news` |
| 9 | РБК RSS | `https://rssexport.rbc.ru/rbcnews/news/30/full.rss` | `rss` | `rbc` | активен | `raw_news` |
| 10 | Ведомости RSS: банки | `https://www.vedomosti.ru/rss/rubric/finance/banks` | `rss` | `vedomosti` | активен | `raw_news` |
| 11 | Коммерсантъ: финансы | `https://www.kommersant.ru/finance` | `site` | `kommersant` | активен | `raw_news` |

## База Данных

### `sources`

Источники, которые использует парсер.

При `python back\init_db.py` создаётся стартовый набор источников. В `parser_config` лежит имя коннектора, период поиска и параметры конкретного источника. Активны источники 1-11. Для Росстата временно задано `verify_ssl=false`, потому что локальная проверка цепочки сертификата может падать.

| Поле | Описание |
| --- | --- |
| `id` | ID источника |
| `name` | Название источника |
| `url` | Ссылка, которую читает парсер |
| `source_type` | Грубый тип источника: `rss`, `site`, `api`, `telegram`; конкретный коннектор хранится в `parser_config.connector` |
| `is_active` | Использовать ли источник |
| `parse_frequency_minutes` | Как часто источник нужно проверять |
| `parser_config` | JSON-строка с настройками селекторов парсера |
| `last_parsed_at` | Когда источник последний раз проверяли |
| `created_at` | Когда источник добавлен |
| `updated_at` | Когда источник обновлен |

### `raw_news`

Сырые новости, найденные парсером.

| Поле | Описание |
| --- | --- |
| `id` | ID новости |
| `source_id` | Ссылка на `sources.id` |
| `url` | Ссылка на конкретную новость |
| `title` | Заголовок новости |
| `text` | Сырой текст новости |
| `published_at` | Дата публикации новости |
| `parsed_at` | Когда новость была найдена парсером |
| `status` | `new`, `processing`, `processed`, `skipped`, `error` |
| `content_hash` | Хеш текста/заголовка для поиска дублей |
| `raw_data` | Дополнительные данные парсера в JSON-строке |
| `error_message` | Текст ошибки, если обработка упала |

### `moex_daily_stats`

Дневная агрегированная статистика MOEX ISS. Одна строка соответствует одному торговому дню.

| Поле | Описание |
| --- | --- |
| `id` | ID записи |
| `source_id` | Ссылка на `sources.id` |
| `trade_date` | Дата торгов |
| `securities_count` | Сколько инструментов попало в дневную сводку |
| `traded_securities_count` | Сколько инструментов реально торговалось |
| `total_value` | Суммарный оборот |
| `total_value_usd` | Суммарный оборот в USD, если MOEX отдал это поле |
| `total_volume` | Суммарный объем |
| `total_trades` | Суммарное количество сделок |
| `average_last` | Среднее значение последней цены по инструментам, где оно есть |
| `average_marketprice` | Средняя рыночная цена по инструментам, где она есть |
| `top_secid` | Инструмент с максимальным оборотом |
| `top_shortname` | Короткое название инструмента с максимальным оборотом |
| `top_value` | Оборот инструмента-лидера |
| `top_volume_secid` | Инструмент с максимальным объемом |
| `top_volume_shortname` | Короткое название инструмента с максимальным объемом |
| `top_volume` | Объем инструмента-лидера |
| `top_trades_secid` | Инструмент с максимальным количеством сделок |
| `top_trades_shortname` | Короткое название инструмента с максимумом сделок |
| `top_trades` | Количество сделок инструмента-лидера |
| `moex_systime` | Время последнего обновления в данных MOEX |
| `raw_data` | Сырые строки MOEX ISS, из которых собрана дневная сводка |
| `fetched_at` | Когда запись получена |

### `signals`

Готовые чистые карточки после обработки моделью.

| Поле | Описание |
| --- | --- |
| `id` | ID сигнала |
| `raw_news_id` | Ссылка на `raw_news.id` |
| `headline` | Короткий заголовок |
| `hotness` | Важность сигнала от 0 до 100 |
| `why_now` | Почему это важно сейчас |
| `category` | Категория |
| `summary` | Короткая выжимка |
| `draft` | Черновик поста, заметки или сообщения |
| `moderation_status` | `pending`, `approved`, `rejected`, `needs_review` |
| `confidence` | Уверенность модели от 0 до 1 |
| `model_name` | Название модели |
| `prompt_version` | Версия промпта |
| `created_at` | Когда карточка создана |
| `updated_at` | Когда карточка обновлена |

## Коннекторы

```text
back/
  parser.py
  connectors/
    base.py
    generic.py
    cbr.py
    minfin.py
    rosstat.py
    moex.py
    alfabank.py
    sber.py
    tbank.py
    vtb.py
    rbc.py
    vedomosti.py
    kommersant.py
```