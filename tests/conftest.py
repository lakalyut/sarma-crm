import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

# app/render.py и app/main.py создают свои собственные SessionLocal() в обход
# FastAPI Depends(get_db) — переопределить зависимость на роуте недостаточно,
# нужно направить сам глобальный engine на тестовую БД до первого импорта
# app.database. Тот же sqlite-файл, что уже использует CI (ci.yml).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

# Мидлварь CSRF (app/csrf.py) сверяет cookie csrf_token с одноимённым полем
# формы на каждом POST/PUT/PATCH/DELETE. Фикстуры сразу выставляют cookie —
# тесты, которые шлют POST, обязаны передавать data={"csrf_token": CSRF_TOKEN, ...}.
CSRF_TOKEN = "test-csrf-token"


@pytest.fixture()
def db_session():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    c = TestClient(app)
    c.cookies.set("csrf_token", CSRF_TOKEN)
    return c


@pytest.fixture()
def admin_user(db_session):
    from app.auth_models import User
    from app.auth_security import hash_password

    user = User(
        email="admin@test.local",
        password_hash=hash_password("test-password-123"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def signed_init_data(telegram_id: int, first_name: str = "Тест") -> str:
    """Собирает валидно подписанную Telegram WebApp initData тем же алгоритмом,
    что app/telegram_auth.py::verify_init_data — подписывает TELEGRAM_TOKEN из
    окружения (грузится из .env через load_dotenv() при импорте app.main выше,
    тот же тестовый бот, что и на Этапе 0)."""
    token = os.environ["TELEGRAM_TOKEN"]
    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(
            {"id": telegram_id, "first_name": first_name}, ensure_ascii=False
        ),
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(data)


@pytest.fixture()
def admin_client(client, db_session, admin_user):
    from app.auth_models import SessionModel, default_expiry, new_session_id

    sid = new_session_id()
    db_session.add(
        SessionModel(id=sid, user_id=admin_user.id, expires_at=default_expiry(hours=1))
    )
    db_session.commit()
    client.cookies.set("session_id", sid)
    return client
