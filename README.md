# Fintech Trendwatcher

Сервис для поиска финтех-сигналов: парсер собирает новости, документы и API-данные, модель позже превращает их в карточки, backend дает доступ к данным.

## Запуск

```powershell
python back\init_db.py # создать/обновить текущую БД и стартовые источники
python back\app.py
```

Backend поднимается на:

```text
http://127.0.0.1:5000
```

## Парсинг

Период поиска по умолчанию: последние 3 дня.

Запустить парсер по всем активным источникам из таблицы `sources`:

```text
http://127.0.0.1:5000/parser
```

Запустить парсер по одному источнику:

```text
http://127.0.0.1:5000/parser/source/1
```

Ответ парсера содержит сводку по каждому источнику: откуда запускался парсинг, сколько записей найдено, сколько сохранено, сколько было дублей и были ли ошибки.

```json
{
  "parser": {
    "created": 8,
    "duplicates": 2,
    "errors": 0,
    "empty_sources": 0,
    "summary": [
      "РБК RSS (https://rssexport.rbc.ru/rbcnews/news/30/full.rss): найдено 10, сохранено 8, дублей 2"
    ]
  }
}
```

`skipped` оставлен как старое имя для дублей: если URL уже есть в `raw_news`, запись не вставляется повторно и учитывается в `duplicates`.

## Источники

Стартовый список источников создается в `sources` при запуске `python back\init_db.py`.

| ID | Источник | URL | Тип | Адаптер | Статус |
|---:|---|---|---|---|---|
| 1 | Банк России: новости | `https://www.cbr.ru/scripts/XML_News.asp` | `api` | `xml` | активен |
| 2 | Минфин России: пресс-центр | `https://minfin.gov.ru/ru/press-center/` | `site` | `html` | активен |
| 3 | Росстат: национальные счета | `https://rosstat.gov.ru/statistics/accounts` | `site` | `html_files` | активен, `verify_ssl=false` |
| 4 | MOEX ISS shares | `https://iss.moex.com/iss/engines/stock/markets/shares/securities.json` | `api` | `json` | активен |
| 5 | Альфа-Банк: новости | `https://alfabank.ru/news/t/` | `site` | `html` | активен |
| 6 | Сбер: пресс-релизы | `https://www.sberbank.com/ru/news-and-media/press-releases` | `site` | `html_files` | активен |
| 7 | Т-Банк: новости | `https://www.tbank.ru/about/news/` | `site` | `html` | активен |
| 8 | ВТБ: пресс-центр и IR | `https://www.vtb.com/about/press-center/` | `site` | `html_files` | активен |
| 9 | РБК RSS | `https://rssexport.rbc.ru/rbcnews/news/30/full.rss` | `rss` | `rss` | активен |
| 10 | Ведомости RSS: банки | `https://www.vedomosti.ru/rss/rubric/finance/banks` | `rss` | `rss` | активен |
| 11 | Коммерсантъ: архив новостей | `https://www.kommersant.ru/archive/news` | `site` | `html` | активен |
| 12 | Yandex Search API discovery | `https://searchapi.api.cloud.yandex.net/v2/web/searchAsync` | `api` | `yandex_search` | выключен, нужны `YANDEX_API_KEY` и `YANDEX_FOLDER_ID` |

Для пополнения списка консольный скрипт:

```powershell
python back\update_sources.py
```

## Тесты

Новые тесты в `tests/`, файлы должны называться `test_*.py`.

Запуск:

```text
http://127.0.0.1:5000/tests/all
http://127.0.0.1:5000/tests/db
```

Тесты также запускаются:

- на `push` и `pull_request` через GitHub Actions;
- перед `commit`, `push` и `merge` через локальные git hooks из `.githooks`.
