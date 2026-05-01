# База данных

## Таблицы

### `sources`

Источники, которые использует парсер.

При `python back\init_db.py` создаётся стартовый набор источников:

```text
1. Банк России: новости -> https://www.cbr.ru/scripts/XML_News.asp
2. Минфин России: пресс-центр -> https://minfin.gov.ru/ru/press-center/
3. Росстат: национальные счета -> https://rosstat.gov.ru/statistics/accounts
4. MOEX ISS shares -> https://iss.moex.com/iss/engines/stock/markets/shares/securities.json
5. Альфа-Банк: новости -> https://alfabank.ru/news/t/
6. Сбер: пресс-релизы -> https://www.sberbank.com/ru/news-and-media/press-releases
7. Т-Банк: новости -> https://www.tbank.ru/about/news/
8. ВТБ: пресс-центр и IR -> https://www.vtb.com/about/press-center/
9. РБК RSS -> https://rssexport.rbc.ru/rbcnews/news/30/full.rss
10. Ведомости RSS: банки -> https://www.vedomosti.ru/rss/rubric/finance/banks
11. Коммерсантъ: архив новостей -> https://www.kommersant.ru/archive/news
12. Yandex Search API discovery -> https://searchapi.api.cloud.yandex.net/v2/web/searchAsync
```

В `parser_config` лежат тип адаптера, период поиска по умолчанию 3 дня, селекторы или параметры API. Для Росстата временно задано `verify_ssl=false`, потому что локальная проверка цепочки сертификата может падать. Yandex Search API по умолчанию выключен, потому что требует `YANDEX_API_KEY` и `YANDEX_FOLDER_ID`.

Добавить или обновить источник локально:

```powershell
python back\update_sources.py
```

Параметры вводятся в консоли. Перед сохранением скрипт делает тестовый запрос и показывает, сколько новостей нашёл.

```json
{
  "kind": "html",
  "max_age_days": 3,
  "link_selector": "a.g-inline-text-badges.js-item-link",
  "date_selectors": null,
  "text_selector": "article p",
  "pause": 0.5,
  "timeout": 15,
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
  "use_fallback_date_search": true,
  "date_formats": null
}
```

| Поле | Описание |
| --- | --- |
| `id` | ID источника |
| `name` | Название источника |
| `url` | Ссылка, которую читает парсер |
| `source_type` | Грубый тип источника: `rss`, `site`, `api`, `telegram`; конкретный адаптер хранится в `parser_config.kind` |
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
