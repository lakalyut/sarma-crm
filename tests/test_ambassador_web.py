import re

CSRF_TOKEN = "test-csrf-token"


def _extract_token(html: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_\-]+)", html)
    assert match, "password-set link not found in response"
    return match.group(1)


def _create_ambassador(admin_client, email="amb-web@example.com"):
    resp = admin_client.post(
        "/admin/users/new",
        data={
            "email": email,
            "role": "ambassador",
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert resp.status_code == 200
    return _extract_token(resp.text)


def test_create_ambassador_without_telegram_id_gets_password_link(
    admin_client, db_session
):
    from app.auth_models import User

    token = _create_ambassador(admin_client)
    assert token

    user = db_session.query(User).filter(User.email == "amb-web@example.com").first()
    assert user is not None
    assert user.telegram_id is None
    assert user.password_hash is None


def test_ambassador_can_set_password_and_login(admin_client, client, db_session):
    from app.auth_models import User

    token = _create_ambassador(admin_client, email="amb-login@example.com")

    resp = client.post(
        "/auth/set-password",
        data={
            "token": token,
            "password": "ambassador-pass-123",
            "password2": "ambassador-pass-123",
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert resp.status_code == 200

    user = db_session.query(User).filter(User.email == "amb-login@example.com").first()
    assert user.password_hash is not None

    resp = client.post(
        "/auth/login",
        data={
            "email": "amb-login@example.com",
            "password": "ambassador-pass-123",
            "csrf_token": CSRF_TOKEN,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "session_id" in resp.cookies


def _login_ambassador(client, db_session, city=None, first_name=None):
    from app.auth_models import SessionModel, User, default_expiry, new_session_id
    from app.auth_security import hash_password

    user = User(
        email="amb-flow@example.com",
        password_hash=hash_password("test-password-123"),
        role="ambassador",
        is_active=True,
        first_name=first_name,
        city=city,
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
    return user


def test_visit_page_redirects_to_profile_when_incomplete(client, db_session):
    _login_ambassador(client, db_session)

    resp = client.get("/ambassador/visit", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ambassador/profile"


def test_profile_submit_completes_and_unlocks_visit_page(client, db_session):
    from app.models import Sale

    db_session.add(
        Sale(
            city="Тестгород",
            month="2026-01-01",
            type="Кальянная",
            client="Клиент",
            qty=1,
            weight=1,
        )
    )
    db_session.commit()

    _login_ambassador(client, db_session)

    resp = client.post(
        "/ambassador/profile",
        data={
            "first_name": "Иван",
            "last_name": "Иванов",
            "city": "Тестгород",
            "csrf_token": CSRF_TOKEN,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ambassador/visit"

    resp = client.get("/ambassador/visit")
    assert resp.status_code == 200


def test_profile_submit_rejects_unknown_city(client, db_session):
    from app.models import Sale

    db_session.add(
        Sale(
            city="Тестгород",
            month="2026-01-01",
            type="Кальянная",
            client="Клиент",
            qty=1,
            weight=1,
        )
    )
    db_session.commit()

    _login_ambassador(client, db_session)

    resp = client.post(
        "/ambassador/profile",
        data={
            "first_name": "Иван",
            "last_name": "Иванов",
            "city": "Город, которого нет",
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert resp.status_code == 200
    assert "Выберите город из списка" in resp.text


def test_visit_submit_happy_path_and_invalid_city(client, db_session):
    from app.models import Product, Sale, Visit

    db_session.add(
        Sale(
            city="Город",
            month="2026-01-01",
            type="Кальянная",
            client="Клиент",
            qty=1,
            weight=1,
        )
    )
    product = Product(
        category="Табак",
        brand="Бренд",
        flavor="Мята",
        canonical_sku="WEB-SKU",
        canonical_name="Бренд Мята",
        norm_brand="бренд",
        norm_flavor="мята",
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    _login_ambassador(client, db_session, city="Город", first_name="Иван")

    resp = client.post(
        "/ambassador/visit",
        data={
            "city": "Не тот город",
            "client": "Клиент",
            "sale_type": "Кальянная",
            "product_ids": [product.id],
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert resp.status_code == 200
    assert "Визит записан" not in resp.text
    assert "message error" in resp.text

    resp = client.post(
        "/ambassador/visit",
        data={
            "city": "Город",
            "client": "Клиент",
            "sale_type": "Кальянная",
            "product_ids": [product.id],
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert resp.status_code == 200
    assert "Визит записан" in resp.text
    assert db_session.query(Visit).count() == 1


def test_leaderboard_page_accessible_to_ambassador(client, db_session):
    _login_ambassador(client, db_session, city="Город лидерборда", first_name="Иван")

    resp = client.get("/ambassador/leaderboard")
    assert resp.status_code == 200
