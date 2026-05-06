# Production Deploy

Production Docker setup is in `docker-compose.prod.yml`.

The backend is exposed only on `127.0.0.1:${BACKEND_PORT}:5000`, so Nginx can proxy the public domain to it.

The app uses the existing SQLite setup via `DB_PATH`. The VPS `./data` directory is mounted into the container as `/app/data`, so `./data/app.db` stays outside the image and is preserved between rebuilds.

## First Setup On VPS

```bash
sudo mkdir -p /opt/myapp
sudo chown "$USER":"$USER" /opt/myapp
cd /opt/myapp
git clone https://github.com/onixal/fintech-trendwatcher-alpha.git .
mkdir -p data
cp .env.example .env
nano .env
docker compose -f docker-compose.prod.yml up -d --build
```

Before the first production start, put the existing SQLite database at:

```text
/opt/myapp/data/app.db
```

For example, from your local machine:

```bash
scp data/app.db user@your-vps-host:/opt/myapp/data/app.db
```

If this file is missing, the container will start, but the parser will not have the existing configured sources/data.

## Update Deploy

```bash
cd /opt/myapp
git fetch origin main
git reset --hard origin/main
mkdir -p data
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
docker image prune -f
```

Do not delete `./data/app.db`. Do not run cleanup commands that remove the project `data` directory.

## Useful Commands

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f backend
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
