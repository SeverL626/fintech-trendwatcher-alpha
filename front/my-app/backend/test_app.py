import pytest
import json
import sqlite3
import app as app_module
from app import create_app, db, User, SignalCard, Favorite, NotificationSetting


@pytest.fixture
def app(tmp_path):
    main_db_path = tmp_path / "app.db"
    with sqlite3.connect(main_db_path) as conn:
        conn.executescript("""
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                url TEXT NOT NULL
            );
            CREATE TABLE raw_news (
                id INTEGER PRIMARY KEY,
                source_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                text TEXT NOT NULL,
                published_at TEXT,
                parsed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'processed'
            );
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY,
                headline TEXT NOT NULL,
                hotness INTEGER NOT NULL,
                why_now TEXT,
                category TEXT NOT NULL,
                sources TEXT NOT NULL,
                summary TEXT,
                draft TEXT
            );
            CREATE TABLE moex_daily_stats (
                id INTEGER PRIMARY KEY,
                trade_date TEXT NOT NULL,
                securities_count INTEGER,
                traded_securities_count INTEGER,
                total_value REAL,
                total_trades INTEGER,
                top_secid TEXT,
                top_shortname TEXT,
                top_value REAL
            );
        """)
        conn.execute("INSERT INTO sources (id, name, url) VALUES (1, 'vc.ru', 'https://vc.ru')")
        conn.execute("""
            INSERT INTO raw_news (id, source_id, url, title, text, published_at)
            VALUES (1, 1, 'https://example.com/signal-1', 'KYC test', 'KYC test body', '2026-05-15T10:00:00+00:00')
        """)
        conn.execute("""
            INSERT INTO signals (id, headline, hotness, why_now, category, sources, summary, draft)
            VALUES (1, 'KYC scenario for bank app', 4, 'Нужно проверить KYC.', 'Идентификация и биометрия', '1', 'KYC summary', '')
        """)
    app_module.MAIN_DB_PATH = main_db_path

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': "sqlite:///:memory:",
        'JWT_SECRET_KEY': "test-secret-key-with-at-least-32-bytes"
    })
    with app.app_context():
        db.create_all()
        # seed_data() выполняется автоматически при создании приложения
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    """Фикстура для получения токена обычного пользователя."""
    # Используем данные из SAMPLE_USERS в app.py
    login_data = {"email": "user@redcat.local", "password": "User12345!"}
    res = client.post('/api/login', json=login_data)
    token = res.json['token']
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(client):
    """Фикстура для получения токена администратора."""
    login_data = {"email": "admin@redcat.local", "password": "Admin12345!"}
    res = client.post('/api/login', json=login_data)
    token = res.json['token']
    return {"Authorization": f"Bearer {token}"}


# --- ТЕСТЫ СИГНАЛОВ И ПОИСКА ---

def test_signals_search_filtering(client):
    """Проверка точности поиска по ключевым словам."""
    # Поиск слова, которое точно есть в тестовой основной БД.
    res = client.get('/api/signals?q=KYC')
    assert res.status_code == 200
    for item in res.json['items']:
        assert 'kyc' in item['headline'].lower() or 'kyc' in item['summary'].lower()


def test_get_single_signal_success(client):
    """Проверка получения одной карточки по ID."""
    res = client.get('/api/signals/1')
    assert res.status_code == 200
    assert res.json['item']['id'] == 1


def test_get_single_signal_not_found(client):
    """Проверка ошибки 404 для несуществующего сигнала."""
    res = client.get('/api/signals/999')
    assert res.status_code == 404


# --- ТЕСТЫ ИЗБРАННОГО ---

def test_toggle_favorite_flow(client, auth_headers):
    """Проверка добавления и удаления из избранного."""
    signal_id = 1
    # Добавляем
    res = client.post(f'/api/signals/{signal_id}/favorite', headers=auth_headers)
    assert res.json['saved'] is True

    # Проверяем наличие в списке избранного
    list_res = client.get('/api/favorites', headers=auth_headers)
    assert any(item['id'] == signal_id for item in list_res.json['items'])

    # Удаляем (повторный запрос)
    res = client.post(f'/api/signals/{signal_id}/favorite', headers=auth_headers)
    assert res.json['saved'] is False


# --- ТЕСТЫ УВЕДОМЛЕНИЙ ---

def test_notification_settings_persistence(client, auth_headers):
    """Проверка сохранения настроек уведомлений."""
    rules = {
        "rules": [
            {"theme": "UX-механика", "hotness_min": 4},
            {"source_name": "vc.ru"}
        ]
    }
    res = client.put('/api/notification-settings', json=rules, headers=auth_headers)
    assert res.status_code == 200

    # Проверяем, что настройки применились
    get_res = client.get('/api/notification-settings', headers=auth_headers)
    assert len(get_res.json['items']) == 2


# --- ТЕСТЫ АДМИН-ПАНЕЛИ ---

def test_admin_promo_management(client, admin_headers):
    """Проверка создания и изменения промокода админом."""
    # Создание
    new_promo = {"code": "NEW2026", "description": "Test promo"}
    res = client.post('/api/admin/promo-codes', json=new_promo, headers=admin_headers)
    assert res.status_code == 200
    promo_id = res.json['item']['id']

    # Деактивация
    client.put(f'/api/admin/promo-codes/{promo_id}', json={"active": False}, headers=admin_headers)

    # Проверка статуса
    get_res = client.get('/api/admin/promo-codes', headers=admin_headers)
    target = next(p for p in get_res.json['items'] if p['id'] == promo_id)
    assert target['active'] is False


def test_unauthorized_admin_access(client, auth_headers):
    """Запрет доступа к админским функциям для обычного юзера."""
    res = client.get('/api/admin/users', headers=auth_headers)
    assert res.status_code == 403
