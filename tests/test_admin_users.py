CSRF_TOKEN = "test-csrf-token"  # см. tests/conftest.py


def test_create_ambassador_via_admin_users_new(admin_client, db_session):
    from app.auth_models import User

    resp = admin_client.post(
        "/admin/users/new",
        data={
            "email": "amb@example.com",
            "role": "ambassador",
            "telegram_id": "555444333",
            "csrf_token": CSRF_TOKEN,
        },
    )

    assert resp.status_code == 200

    user = db_session.query(User).filter(User.email == "amb@example.com").first()
    assert user is not None
    assert user.role == "ambassador"
    # Горизонт 13.1 — амбассадор всегда получает ссылку установки пароля
    # (браузерный путь), telegram_id — опциональная надстройка сверху, не
    # альтернатива паролю.
    assert user.password_hash is None  # пароль появится только после /auth/set-password
    assert user.telegram_id == 555444333


def test_ambassador_without_telegram_id_gets_password_link(admin_client, db_session):
    from app.auth_models import User

    resp = admin_client.post(
        "/admin/users/new",
        data={
            "email": "amb-no-id@example.com",
            "role": "ambassador",
            "csrf_token": CSRF_TOKEN,
        },
    )

    assert resp.status_code == 200
    assert "auth/set-password" in resp.text

    user = db_session.query(User).filter(User.email == "amb-no-id@example.com").first()
    assert user is not None
    assert user.telegram_id is None


def test_duplicate_telegram_id_is_rejected_cleanly(admin_client, db_session):
    from app.auth_models import User

    admin_client.post(
        "/admin/users/new",
        data={
            "email": "amb1@example.com",
            "role": "ambassador",
            "telegram_id": "111222333",
            "csrf_token": CSRF_TOKEN,
        },
    )

    resp = admin_client.post(
        "/admin/users/new",
        data={
            "email": "amb2@example.com",
            "role": "ambassador",
            "telegram_id": "111222333",
            "csrf_token": CSRF_TOKEN,
        },
    )

    assert resp.status_code == 200
    assert (
        db_session.query(User).filter(User.email == "amb2@example.com").first() is None
    )


def test_change_role_to_ambassador(admin_client, db_session):
    from app.auth_models import User

    user = User(email="plain@example.com", role="user", is_active=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    resp = admin_client.post(
        f"/admin/users/{user.id}/change-role",
        data={"role": "ambassador", "csrf_token": CSRF_TOKEN},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    db_session.refresh(user)
    assert user.role == "ambassador"


def test_regular_user_still_has_analytics_access(client, db_session):
    from app.auth_models import SessionModel, User, default_expiry, new_session_id
    from app.auth_security import hash_password

    user = User(
        email="regular@example.com",
        password_hash=hash_password("test-password-123"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    sid = new_session_id()
    db_session.add(
        SessionModel(id=sid, user_id=user.id, expires_at=default_expiry(hours=1))
    )
    db_session.commit()
    client.cookies.set("session_id", sid)

    resp = client.get("/events")
    assert resp.status_code == 200
