import json
import re
from html import unescape

import pytest
from conftest import CSRF_TOKEN, signed_init_data

from app.auth_models import SessionModel, User, default_expiry
from app.models import Product, Sale, Visit, VisitProduct
from app.services.leaderboard_service import get_leaderboard


@pytest.fixture
def visitor(db_session):
    user = User(
        email="visitor@test.local",
        role="user",
        telegram_id=5557770001,
        first_name="Иван",
        is_active=True,
        can_create_visits=True,
    )
    product = Product(
        category="Табак",
        brand="Сарма",
        flavor="Мята",
        canonical_sku="SKU",
        canonical_name="Мята",
        norm_brand="сарма",
        norm_flavor="мята",
        is_active=True,
    )
    db_session.add_all([user, product])
    for city in ("Иркутск", "Москва"):
        db_session.add(
            Sale(
                city=city,
                client="Кафе",
                type="HoReCa",
                month="2026-10-01",
                sku="SKU",
                qty=1,
                weight=1,
            )
        )
    db_session.commit()
    return user, product


def payload(product, city="Иркутск"):
    return dict(
        city=city,
        client="Кафе",
        sale_type="HoReCa",
        product_ids=[product.id],
        sku_classic="1",
        sku_strong="0",
        sku_light="2",
        people_count="5",
        goal="Дегустация",
        comment="Визит",
    )


def headers(user):
    return {"Authorization": "tma " + signed_init_data(user.telegram_id)}


def web_login(client, db, user):
    db.add(
        SessionModel(id="visitor-session", user_id=user.id, expires_at=default_expiry())
    )
    db.commit()
    client.cookies.set("session_id", "visitor-session")


def test_enabled_user_records_two_cities_and_appears_in_leaderboard(
    client, db_session, visitor
):
    user, product = visitor
    response = client.post("/ambassador/app/verify", headers=headers(user))
    assert response.json()["can_record_visits"] is True
    assert response.json()["role"] == "user"
    for city in ("Иркутск", "Москва"):
        response = client.post(
            "/ambassador/app/visits", headers=headers(user), json=payload(product, city)
        )
        assert response.status_code == 200
        assert response.json()["demo"] is False
    assert db_session.query(Visit).count() == 2
    assert db_session.query(VisitProduct).count() == 2
    assert {v.ambassador_id for v in db_session.query(Visit)} == {user.id}
    row = get_leaderboard(db_session)[0]
    assert row["visits"] == 2
    assert row["aromas_total"] == 2
    assert row["city"] == "Все города"
    web_login(client, db_session, user)
    assert client.get("/analytics/regions").status_code == 200
    assert client.get("/analytics/client-analysis").status_code == 200


def test_revocation_restores_demo_and_preserves_history(client, db_session, visitor):
    user, product = visitor
    client.post("/ambassador/app/visits", headers=headers(user), json=payload(product))
    user.can_create_visits = False
    db_session.commit()
    response = client.post(
        "/ambassador/app/visits",
        headers=headers(user),
        json={**payload(product), "can_create_visits": True, "dry_run": False},
    )
    assert response.status_code == 200
    assert response.json()["demo"] is True
    assert response.json()["visit_id"] is None
    assert db_session.query(Visit).count() == 1
    assert get_leaderboard(db_session) == []
    assert (
        client.post("/ambassador/app/verify", headers=headers(user)).json()[
            "can_record_visits"
        ]
        is False
    )
    web_login(client, db_session, user)
    assert client.get("/ambassador/visit").status_code == 403


def test_permission_does_not_bypass_validation(client, db_session, visitor):
    user, product = visitor
    data = payload(product)
    data["city"] = "Нет такого города"
    response = client.post("/ambassador/app/visits", headers=headers(user), json=data)
    assert response.status_code == 400
    assert db_session.query(Visit).count() == 0


def test_disabled_user_cannot_verify_or_record(client, db_session, visitor):
    user, product = visitor
    user.is_active = False
    db_session.commit()
    assert (
        client.post("/ambassador/app/verify", headers=headers(user)).status_code == 403
    )
    assert (
        client.post(
            "/ambassador/app/visits", headers=headers(user), json=payload(product)
        ).status_code
        == 403
    )
    assert db_session.query(Visit).count() == 0


def test_browser_visits_in_any_city_and_city_specific_history(
    client, db_session, visitor
):
    user, product = visitor
    web_login(client, db_session, user)
    page = client.get("/ambassador/visit")
    assert page.status_code == 200
    options_json = re.search(r'data-options="([^"]+)"', page.text).group(1)
    assert set(json.loads(unescape(options_json))["cities"]) == {"Москва", "Иркутск"}
    for city in ("Иркутск", "Москва"):
        response = client.post(
            "/ambassador/visit",
            data={**payload(product, city), "csrf_token": CSRF_TOKEN},
            follow_redirects=False,
        )
        assert response.status_code == 303
        history = client.get(
            "/ambassador/visit-history", params={"city": city, "client": "Кафе"}
        ).json()["history"]
        assert len(history) == 1
    assert db_session.query(Visit).count() == 2


def test_browser_profile_for_enabled_user_does_not_require_city(
    client, db_session, visitor
):
    user, _ = visitor
    user.first_name = None
    db_session.commit()
    web_login(client, db_session, user)
    assert (
        client.get("/ambassador/visit", follow_redirects=False).headers["location"]
        == "/ambassador/profile"
    )
    page = client.get("/ambassador/profile")
    assert 'name="city"' not in page.text
    response = client.post(
        "/ambassador/profile",
        data={"csrf_token": CSRF_TOKEN, "first_name": "Иван"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert client.get("/ambassador/visit").status_code == 200


def test_admin_can_grant_and_revoke_without_changing_role(
    admin_client, db_session, visitor
):
    user, _ = visitor
    for enabled in (False, True):
        data = dict(
            csrf_token=CSRF_TOKEN,
            email=user.email,
            telegram_id=str(user.telegram_id),
            first_name=user.first_name,
        )
        if enabled:
            data["can_create_visits"] = "true"
        response = admin_client.post(f"/admin/users/{user.id}/edit", data=data)
        assert response.status_code == 200
        db_session.refresh(user)
        assert user.role == "user"
        assert user.can_create_visits is enabled
    page = admin_client.get(f"/admin/users/{user.id}/edit")
    assert "Запись реальных визитов" in page.text


def test_user_cannot_grant_self_permission(client, db_session, visitor):
    user, _ = visitor
    user.can_create_visits = False
    db_session.commit()
    web_login(client, db_session, user)
    response = client.post(
        f"/admin/users/{user.id}/edit",
        data={
            "csrf_token": CSRF_TOKEN,
            "email": user.email,
            "can_create_visits": "true",
        },
    )
    assert response.status_code == 403
    db_session.refresh(user)
    assert user.can_create_visits is False


def test_admin_creates_user_with_telegram_and_visit_permission(
    admin_client, db_session
):
    response = admin_client.post(
        "/admin/users/new",
        data={
            "csrf_token": CSRF_TOKEN,
            "email": "new-visitor@test.local",
            "role": "user",
            "telegram_id": "5558880001",
            "can_create_visits": "true",
        },
    )
    assert response.status_code == 200
    user = db_session.query(User).filter_by(email="new-visitor@test.local").one()
    assert user.can_create_visits is True
    assert user.telegram_id == 5558880001


def test_service_cannot_record_unpermitted_user(db_session, visitor):
    from app.services.ambassador_service import create_visit

    user, product = visitor
    user.can_create_visits = False
    db_session.commit()
    with pytest.raises(ValueError, match="не разрешена"):
        create_visit(db_session, user, **payload(product))
    assert db_session.query(Visit).count() == 0
