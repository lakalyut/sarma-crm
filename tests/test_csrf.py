from app.models import Sale

CSRF_TOKEN = "test-csrf-token"  # см. tests/conftest.py


def test_post_without_csrf_cookie_is_rejected(admin_user, db_session):
    from fastapi.testclient import TestClient

    from app.auth_models import SessionModel, default_expiry, new_session_id
    from app.main import app

    # клиент без tests/conftest.py::client — нарочно без csrf_token cookie
    raw_client = TestClient(app)
    sid = new_session_id()
    db_session.add(
        SessionModel(id=sid, user_id=admin_user.id, expires_at=default_expiry(hours=1))
    )
    db_session.commit()
    raw_client.cookies.set("session_id", sid)

    resp = raw_client.post(
        "/admin/imports/delete/preview",
        data={"city": "Москва", "csrf_token": CSRF_TOKEN},
    )

    assert resp.status_code == 403


def test_post_with_mismatched_csrf_token_is_rejected(admin_client):
    resp = admin_client.post(
        "/admin/imports/delete/preview",
        data={"city": "Москва", "csrf_token": "какой-то-другой-токен"},
    )

    assert resp.status_code == 403


def test_post_with_matching_csrf_token_succeeds(admin_client, db_session):
    resp = admin_client.post(
        "/admin/imports/delete/preview",
        data={"city": "Москва", "csrf_token": CSRF_TOKEN},
    )

    assert resp.status_code == 200
    assert db_session.query(Sale).count() == 0


def test_get_requests_do_not_require_csrf_token(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200


def test_can_still_logout_from_a_403_error_page(client, db_session):
    # Регрессия: обработчики ошибок (401/403/404/500) в app/main.py рендерят
    # шаблон напрямую через templates.TemplateResponse, в обход render() —
    # если забыть положить csrf_token в контекст, csrf.js подставит в форму
    # логаута на самой странице ошибки пустое значение, оно не совпадёт с
    # cookie, и сам POST /auth/logout получит собственный 403 — тупик без
    # выхода со страницы ошибки. Поймано вживую на роли с урезанным доступом
    # (ambassador), но баг общий для любой роли, которая может словить 403.
    from app.auth_models import SessionModel, User, default_expiry, new_session_id
    from app.auth_security import hash_password

    user = User(
        email="restricted@example.com",
        password_hash=hash_password("test-password-123"),
        role="ambassador",
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

    resp = client.get("/leaderboard")
    assert resp.status_code == 403
    assert f'content="{CSRF_TOKEN}"' in resp.text

    resp = client.post(
        "/auth/logout",
        data={"csrf_token": CSRF_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"
