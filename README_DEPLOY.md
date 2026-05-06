# Production Deploy

Production Docker setup is in `docker-compose.prod.yml`.

The backend is exposed only on `127.0.0.1:${BACKEND_PORT}:5000`, so Nginx can proxy the public domain to it. There is no external database port: the app uses the existing SQLite file.

## Runtime Data

The app uses SQLite via `DB_PATH=/app/data/app.db`.

On the VPS, `./data` is mounted into the container as `/app/data`:

```yaml
volumes:
  - type: bind
    source: ./data
    target: /app/data
```

So the production database must live at:

```text
/opt/myapp/data/app.db
```

This file is outside the Docker image and is preserved between rebuilds. Do not delete `/opt/myapp/data` or `/opt/myapp/data/app.db`.

Parser runtime state also lives in `/opt/myapp/data`:

```text
parser.lock
parser_manual_throttle.json
parser_status.json
```

These files are intentionally ignored by git and Docker build context.

## First Setup On VPS

```bash
sudo mkdir -p /opt/myapp
sudo chown "$USER":"$USER" /opt/myapp
cd /opt/myapp
git clone https://github.com/onixal/fintech-trendwatcher-alpha.git .
mkdir -p data
cp .env.example .env
nano .env
```

Before the first production start, put the existing SQLite DB at:

```text
/opt/myapp/data/app.db
```

Example from a local machine:

```bash
scp data/app.db user@your-vps-host:/opt/myapp/data/app.db
```

Start:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

## Update Deploy

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
mkdir -p data
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f
```

Do not use cleanup commands that remove the `data` directory. Do not use `docker compose down -v`.

## Health Check

```bash
curl http://127.0.0.1:5000/
curl http://127.0.0.1:5000/parser/status
```

## Parser Routes

Manual parser start:

```text
GET /parser
```

The endpoint returns immediately with `202 Started`; parsing continues in the background. Manual starts are limited to one accepted request every 60 minutes. If a parser run is already active, the response is `409 busy`.

Parser status:

```text
GET /parser/status
```

States: `idle`, `running`, `finished`, `failed`, `timed_out`. The status timeout is 1 hour.

Auto parser schedule:

```text
06:00 and 18:00 Europe/Moscow
```

## GitHub Actions Deploy

Workflow: `.github/workflows/deploy.yml`.

Required secrets:

```text
VPS_HOST
VPS_USER
VPS_SSH_KEY
VPS_SSH_PORT
```

The deploy command keeps `/opt/myapp/data/app.db` in place:

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
mkdir -p data
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f
```

## Nginx Example

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
