import pytest
from conftest import CSRF_TOKEN, signed_init_data
from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.auth_models import SessionModel, User, UserCity, default_expiry
from app.models import CityRegion, EventLog, Product, Region, Sale, Visit
from app.services.ambassador_service import create_visit
from app.services.cities_service import rename_city
from app.services.city_access_service import apply_city_scope
from app.services.leaderboard_service import get_leaderboard


@pytest.fixture
def brand(db_session):
    user = User(
        email="brand@test.local",
        role="brand_ambassador",
        city="Иркутск",
        first_name="Бренд",
        telegram_id=5558880001,
        is_active=True,
    )
    user.city_assignments = [UserCity(city="Иркутск"), UserCity(city="Москва")]
    other = User(
        email="outside@test.local",
        role="ambassador",
        city="Казань",
        first_name="Внешний",
    )
    product = Product(
        category="Табак",
        brand="Сарма",
        flavor="Мята",
        canonical_sku="Мята",
        canonical_name="Мята",
        norm_brand="сарма",
        norm_flavor="мята",
        is_active=True,
    )
    region = Region(name="Общий регион")
    db_session.add_all([user, other, product, region])
    db_session.flush()
    for city in ("Иркутск", "Москва", "Казань"):
        db_session.add(
            Sale(
                city=city,
                month="2026-10-01",
                client="Секретный клиент" if city == "Казань" else "Кафе",
                type="HoReCa",
                product_id=product.id,
                sku="Мята",
                qty=1000 if city == "Казань" else 1,
                weight=1000 if city == "Казань" else 1,
            )
        )
        db_session.add(CityRegion(city=city, region_id=region.id))
        db_session.add(EventLog(city=city))
    db_session.add(
        Visit(
            ambassador_id=other.id,
            city="Казань",
            client="Секретный клиент",
            sale_type="HoReCa",
            comment="Секретная заметка",
        )
    )
    db_session.commit()
    return user, product


def login(client, db, user):
    db.add(
        SessionModel(id="brand-session", user_id=user.id, expires_at=default_expiry())
    )
    db.commit()
    client.cookies.set("session_id", "brand-session")


def headers(user):
    return {"Authorization": "tma " + signed_init_data(user.telegram_id)}


def payload(product, city="Иркутск"):
    return dict(
        city=city,
        client="Кафе",
        sale_type="HoReCa",
        product_ids=[product.id],
        sku_classic=1,
        sku_strong=0,
        sku_light=0,
        people_count=2,
        goal="Дегустация",
        comment="Визит",
    )


def test_sql_scope_covers_aggregates_aliases_and_region_members(db_session, brand):
    from app.services.dashboard_service import get_regions_overview
    from app.services.home_service import get_home_overview

    apply_city_scope(db_session, brand[0])
    assert db_session.query(func.sum(Sale.qty)).scalar() == 2
    alias = aliased(Sale)
    assert db_session.query(func.sum(alias.weight)).scalar() == 2
    assert {city for (city,) in db_session.query(Sale.city).distinct()} == {
        "Иркутск",
        "Москва",
    }
    assert {row.city for row in db_session.query(CityRegion)} == {"Иркутск", "Москва"}
    assert db_session.query(Visit).count() == 0
    assert db_session.query(EventLog).count() == 2
    assert get_home_overview(db_session, 2026)["metrics"]["weight"] == 2
    overview = get_regions_overview(
        db_session,
        ["Иркутск", "Москва", "Казань"],
        [],
        {"Иркутск": "Общий регион", "Москва": "Общий регион", "Казань": "Общий регион"},
    )
    assert overview["metrics"]["qty"]["grand"] == 2
    assert sum(overview["metrics"]["qty"]["city_totals"].values()) == 2


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/analytics/clients",
        "/analytics/charts",
        "/analytics/client-analysis",
        "/analytics/regions",
        "/events",
    ],
)
def test_analytics_pages_hide_other_cities(client, db_session, brand, path):
    login(client, db_session, brand[0])
    response = client.get(path)
    assert response.status_code == 200
    assert "Казань" not in response.text
    assert "Секретный клиент" not in response.text
    assert "Секретная заметка" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/analytics/clients?city=Казань",
        "/api/charts/metrics?city=Казань",
        "/api/client-analysis/clients?city=Казань&sale_type=HoReCa",
        "/analytics/client-analysis?city=Казань&download=1",
        "/analytics/regions?cities=Казань",
    ],
)
def test_tampered_query_cannot_access_foreign_city(client, db_session, brand, path):
    login(client, db_session, brand[0])
    response = client.get(path)
    assert response.status_code == 403
    assert "Секретный клиент" not in response.text


def test_telegram_analytics_multi_city_but_visits_only_registered_city(
    client, db_session, brand
):
    user, product = brand
    auth = headers(user)
    assert (
        client.post("/ambassador/app/verify", headers=auth).json()["can_record_visits"]
        is True
    )
    assert set(client.get("/ambassador/app/cities", headers=auth).json()["cities"]) == {
        "Иркутск",
        "Москва",
    }
    assert client.get("/ambassador/app/options", headers=auth).json()["cities"] == [
        "Иркутск"
    ]
    assert client.get("/ambassador/app/clients?city=Москва", headers=auth).json()[
        "rows"
    ]
    assert (
        client.get("/ambassador/app/clients?city=Казань", headers=auth).status_code
        == 403
    )
    assert (
        client.post(
            "/ambassador/app/visits", headers=auth, json=payload(product)
        ).json()["demo"]
        is False
    )
    assert (
        client.post(
            "/ambassador/app/visits", headers=auth, json=payload(product, "Москва")
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/ambassador/app/visits", headers=auth, json=payload(product, "Казань")
        ).status_code
        == 400
    )
    assert db_session.query(Visit).filter(Visit.ambassador_id == user.id).count() == 1


def test_leaderboard_remains_global_in_scoped_session_and_telegram(
    client, db_session, brand
):
    apply_city_scope(db_session, brand[0])
    rows = get_leaderboard(db_session)
    assert any(row["ambassador"] == "Внешний" and row["visits"] == 1 for row in rows)
    assert any(row["ambassador"] == "Бренд" for row in rows)
    rows = client.get("/ambassador/app/leaderboard", headers=headers(brand[0])).json()[
        "rows"
    ]
    assert any(row["visits"] == 1 and row["city"] == "Казань" for row in rows)


def test_no_assignments_is_closed_and_revocation_blocks_service(db_session, brand):
    user, product = brand
    user.city_assignments.clear()
    db_session.commit()
    apply_city_scope(db_session, user)
    assert db_session.query(func.sum(Sale.qty)).scalar() is None
    assert not user.can_record_visits
    with pytest.raises(ValueError, match="городе регистрации"):
        create_visit(db_session, user, **payload(product))


def test_registration_cannot_expand_access_or_change_registered_city(
    client, db_session, brand
):
    login(client, db_session, brand[0])
    response = client.post(
        "/ambassador/profile",
        data={"first_name": "Бренд", "city": "Москва", "csrf_token": CSRF_TOKEN},
    )
    assert "Город регистрации меняет администратор" in response.text
    db_session.refresh(brand[0])
    assert brand[0].city == "Иркутск"


def test_admin_assignments_and_rename_remain_consistent(
    admin_client, db_session, brand
):
    user = brand[0]
    response = admin_client.post(
        f"/admin/users/{user.id}/edit",
        data={
            "email": user.email,
            "city": "Иркутск",
            "assigned_cities": ["Москва"],
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.allowed_cities == ["Москва"]
    assert user.city is None
    rename_city(db_session, "Москва", "Московский город")
    db_session.refresh(user)
    assert user.allowed_cities == ["Московский город"]


def test_admin_can_create_brand_and_role_change_clears_assignments(
    admin_client, db_session, brand
):
    response = admin_client.post(
        "/admin/users/new",
        data={
            "email": "newbrand@test.local",
            "role": "brand_ambassador",
            "assigned_cities": ["Москва"],
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert response.status_code == 200
    user = db_session.query(User).filter(User.email == "newbrand@test.local").one()
    assert user.allowed_cities == ["Москва"]
    admin_client.post(
        f"/admin/users/{user.id}/change-role",
        data={"role": "user", "csrf_token": CSRF_TOKEN},
    )
    db_session.refresh(user)
    assert db_session.query(UserCity).filter(UserCity.user_id == user.id).count() == 0


def test_invalid_telegram_keeps_brand_role_and_city_selection(
    admin_client, db_session, brand
):
    response = admin_client.post(
        "/admin/users/new",
        data={
            "email": "errorbrand@test.local",
            "role": "brand_ambassador",
            "assigned_cities": ["Москва"],
            "telegram_id": "invalid",
            "csrf_token": CSRF_TOKEN,
        },
    )
    assert 'value="brand_ambassador" selected' in response.text
    assert 'value="Москва" checked' in response.text
    assert (
        db_session.query(User).filter(User.email == "errorbrand@test.local").count()
        == 0
    )


@pytest.mark.parametrize(
    "tab",
    ["summary", "ambassadors", "visit_effectiveness", "visit_analysis", "sku_presence"],
)
def test_allowed_report_and_export_do_not_leak_other_cities(
    client, db_session, brand, tab
):
    login(client, db_session, brand[0])
    for download in (0, 1):
        response = client.get(
            "/analytics/client-analysis",
            params={"city": "Москва", "tab": tab, "download": download},
        )
        assert response.status_code == 200
        assert "Секретный клиент" not in response.text
        assert "Секретная заметка" not in response.text


def test_browser_registration_and_visit_are_bound_to_registered_city(
    client, db_session, brand
):
    user, product = brand
    user.city = None
    db_session.commit()
    login(client, db_session, user)
    page = client.get("/ambassador/profile")
    assert page.status_code == 200
    assert "Казань" not in page.text
    response = client.post(
        "/ambassador/profile",
        data={"first_name": "Бренд", "city": "Москва", "csrf_token": CSRF_TOKEN},
    )
    assert response.status_code == 200
    db_session.refresh(user)
    assert user.city == "Москва"
    data = {**payload(product, "Иркутск"), "csrf_token": CSRF_TOKEN}
    response = client.post("/ambassador/visit", data=data)
    assert "городе регистрации" in response.text
    assert db_session.query(Visit).filter(Visit.ambassador_id == user.id).count() == 0


def test_scopes_do_not_leak_between_users_or_query_cache(db_session, brand):
    apply_city_scope(db_session, brand[0])
    assert db_session.query(func.sum(Sale.qty)).scalar() == 2
    second = User(
        email="secondbrand@test.local",
        role="brand_ambassador",
        city="Казань",
        city_assignments=[UserCity(city="Казань")],
    )
    db_session.add(second)
    db_session.commit()
    apply_city_scope(db_session, second)
    assert db_session.query(func.sum(Sale.qty)).scalar() == 1000
    apply_city_scope(db_session, User(role="user"))
    assert db_session.query(func.sum(Sale.qty)).scalar() == 1002


def test_brand_cannot_access_admin_and_import(client, db_session, brand):
    login(client, db_session, brand[0])
    for path in ("/admin/users", "/admin/regions", "/import-xlsx"):
        assert client.get(path).status_code == 403


def test_telegram_registration_offers_only_assignments(db_session, brand, monkeypatch):
    from app.services import telegram_bot_service as bot

    user = brand[0]
    user.city = None
    user.first_name = None
    db_session.commit()
    sent = []
    monkeypatch.setattr(
        bot, "send_message", lambda *args, **kwargs: sent.append((args, kwargs))
    )
    monkeypatch.setattr(bot, "answer_callback_query", lambda *args, **kwargs: None)
    monkeypatch.setattr(bot, "set_chat_menu_button", lambda *args, **kwargs: None)
    bot.handle_update(
        db_session,
        {
            "message": {
                "from": {"id": user.telegram_id},
                "chat": {"id": user.telegram_id},
                "text": "Иван Иванов",
            }
        },
        "https://test.local",
    )
    keyboard = sent[-1][1]["reply_markup"]["inline_keyboard"]
    assert {row[0]["text"] for row in keyboard} == {"Иркутск", "Москва"}
    for city in ("Казань", "Москва"):
        bot.handle_update(
            db_session,
            {
                "callback_query": {
                    "id": "callback",
                    "from": {"id": user.telegram_id},
                    "message": {"chat": {"id": user.telegram_id}},
                    "data": "city:" + city,
                }
            },
            "https://test.local",
        )
        db_session.refresh(user)
        assert user.city is None if city == "Казань" else user.city == "Москва"
