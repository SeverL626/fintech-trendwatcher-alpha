# Project Saver

Это законсервированный репозиторий Red Cat Trendwatcher.

## Состав

- `data/app.db` - основная SQLite-база
- `data/redcat.db` - база frontend-backend
- полный код + конфиги
- презентация


## Адреса

```text
frontend:         http://localhost:5173
backend:          http://localhost:5000
frontend-backend: http://localhost:5001
```

## Deploy

На VPS:

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
cp .env.example .env
nano .env
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
```

В `.env` задать:

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
