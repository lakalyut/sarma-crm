import os

# app/render.py и app/main.py создают свои собственные SessionLocal() в обход
# FastAPI Depends(get_db) — переопределить зависимость на роуте недостаточно,
# нужно направить сам глобальный engine на тестовую БД до первого импорта
# app.database. Тот же sqlite-файл, что уже использует CI (ci.yml).
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


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
    return TestClient(app)


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
