# Project Snapshot

Этот репозиторий законсервирован как готовый рабочий снапшот Red Cat Trendwatcher.

## Что входит в снапшот

- `data/app.db` - основная SQLite-база: источники, сырые новости, сигналы, MOEX, дайджесты.
- `data/redcat.db` - база frontend-backend: пользователи, подписки, избранное, уведомления.
- Код backend, frontend, frontend-backend, модели и Docker-конфиги.
- Презентация проекта в корне репозитория.

Старые backup-БД, server logs, `.env` и локальные `scripts/` в git не кладутся.

## Быстрый запуск локально

```powershell
git clone https://github.com/SeverL626/fintech-trendwatcher-alpha.git
cd fintech-trendwatcher-alpha
copy .env.example .env
```

Заполнить в `.env` минимум:

```env
OPENROUTER_API_KEY=sk-or-v1-...
JWT_SECRET_KEY=<long-random-string>
UPDATE_STATUS_TOKEN=<status-token>
```

Запуск:

```powershell
docker compose up -d --build
```

Адреса:

```text
frontend:         http://localhost:5173
backend:          http://localhost:5000
frontend-backend: http://localhost:5001
```

## Production

На VPS:

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
cp .env.example .env
nano .env
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
```

В `.env` на сервере задать:

```env
OPENROUTER_API_KEY=sk-or-v1-...
JWT_SECRET_KEY=<long-random-string>
UPDATE_STATUS_TOKEN=<status-token>
BACKEND_PORT=5000
FRONT_BACKEND_PORT=5001
FRONTEND_PORT=5173
```

Проверка:

```bash
curl http://127.0.0.1:5000/update/status?token=$UPDATE_STATUS_TOKEN
curl http://127.0.0.1:5001/api/health
curl http://127.0.0.1:5173
```

## Важные правила

- Не коммитить `.env`.
- Не удалять `data/app.db` и `data/redcat.db`, если нужен сохраненный снапшот.
- Не запускать `docker compose down -v` на проде, если данные должны сохраниться.
- После клона с Git LFS убедиться, что базы скачались:

```bash
git lfs pull
ls -lh data/app.db data/redcat.db
```

Если `data/app.db` выглядит как маленький текстовый pointer-файл, значит LFS-объекты не скачались.
