# Project Snapshot

Этот законсервированный репозиторий Red Cat Trendwatcher.

## Состав консервы

- `data/app.db` - основная SQLite-база: источники, сырые новости, сигналы, MOEX, дайджесты.
- `data/redcat.db` - база frontend-backend: пользователи, подписки, избранное, уведомления.
- Код backend, frontend, frontend-backend, модели и Docker-конфиги.
- Презентация проекта в корне репозитория.

Старые backup-БД, server logs, `.env` и локальные `scripts/` **НЕ** сохранены.

## Запуск

```powershell
git clone https://github.com/SeverL626/fintech-trendwatcher-alpha.git
cd fintech-trendwatcher-alpha
copy .env.example .env
```

Заполнить в `.env` (минимум):

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

```bash
git lfs pull
ls -lh data/app.db data/redcat.db
```

> Если `data/app.db` выглядит как маленький текстовый pointer-файл, значит LFS-объекты не скачались.