import pytest

from app.auth_models import SessionModel, User, UserCity, default_expiry, new_session_id
from app.models import CityRegion, EventLog, Region, Sale, Visit
from app.services.cities_service import (
    delete_empty_city,
    get_all_cities,
    get_empty_cities,
)

CSRF = "test-csrf-token"
URL = "/admin/imports/delete/city"
CITY = " Иркутск "


@pytest.fixture
def empty_city(db_session):
    region = Region(name="Восток")
    db_session.add(region)
    db_session.flush()
    db_session.add_all(
        [
            CityRegion(city=CITY, region_id=region.id),
            EventLog(city=CITY, rows_imported=2),
        ]
    )
    db_session.commit()
    return region.id


def post_delete(client, city=CITY, **kwargs):
    return client.post(
        URL, data={"city": city, "confirm": "true", "csrf_token": CSRF}, **kwargs
    )


def add_blocker(db, kind, city=CITY):
    if kind == "sale":
        # A zero-value sale in an old month is still data, not an empty city.
        db.add(Sale(city=city, month="2020-01-01", qty=0, weight=0))
    else:
        user = User(email=f"{kind}@test.local", is_active=False)
        if kind == "profile":
            user.city = city
        db.add(user)
        db.flush()
        if kind == "visit":
            db.add(
                Visit(city=city, ambassador_id=user.id, client="Кафе", sale_type="Бар")
            )
        if kind == "assignment":
            user.role = "brand_ambassador"
            db.add(UserCity(user_id=user.id, city=city))
    db.commit()


def test_lists_exact_empty_names_and_explains_whitespace(
    admin_client, db_session, empty_city
):
    db_session.add(Sale(city="Иркутск", qty=10))
    db_session.commit()
    rows = get_empty_cities(db_session)
    assert len(rows) == 1
    assert rows[0]["name"] == CITY
    assert rows[0]["display_name"] == '" Иркутск "'
    assert rows[0]["can_delete"]
    assert rows[0]["events"] == 1
    assert rows[0]["region"] == "Восток"
    assert "Похожее название" in rows[0]["hints"]
    response = admin_client.get("/admin/imports/delete")
    assert response.status_code == 200
    assert "Удалить пустой город" in response.text
    assert f'value="{CITY}"' in response.text
    assert "Пробелы в начале или конце" in response.text


def test_deletes_exact_variant_and_removes_it_from_city_lists(
    admin_client, db_session, empty_city
):
    db_session.add_all([Sale(city="Иркутск", qty=10), EventLog(city="Иркутск")])
    db_session.commit()
    response = post_delete(admin_client)
    assert response.status_code == 200
    assert "Город « Иркутск » удалён." in response.text
    assert CITY not in get_all_cities(db_session)
    assert "Иркутск" in get_all_cities(db_session)
    assert db_session.query(CityRegion).count() == 0
    assert db_session.query(EventLog).one().city == "Иркутск"
    assert db_session.query(Sale).one().qty == 10
    assert db_session.query(Region).one().id == empty_city


@pytest.mark.parametrize("source", ["event", "region"])
def test_deletes_city_present_only_in_one_metadata_source(
    admin_client, db_session, source
):
    if source == "event":
        db_session.add(EventLog(city=CITY))
    else:
        region = Region(name="Регион")
        db_session.add(region)
        db_session.flush()
        db_session.add(CityRegion(city=CITY, region_id=region.id))
    db_session.commit()
    assert post_delete(admin_client).status_code == 200
    assert CITY not in get_all_cities(db_session)


@pytest.mark.parametrize("kind", ["sale", "visit", "profile", "assignment"])
def test_rechecks_references_added_since_page_was_opened(
    admin_client, db_session, empty_city, kind
):
    response = admin_client.get("/admin/imports/delete")
    assert 'name="city"' in response.text
    add_blocker(db_session, kind)
    response = post_delete(admin_client)
    assert response.status_code == 400
    assert "Город не удалён" in response.text
    assert db_session.query(EventLog).filter_by(city=CITY).count() == 1
    assert db_session.query(CityRegion).filter_by(city=CITY).count() == 1
    assert CITY in get_all_cities(db_session)
    if kind in ("sale", "visit"):
        assert not get_empty_cities(db_session)
    else:
        assert not get_empty_cities(db_session)[0]["can_delete"]


@pytest.mark.parametrize("kind", ["profile", "assignment"])
def test_city_used_by_users_cannot_be_selected(admin_client, db_session, kind):
    add_blocker(db_session, kind)
    response = admin_client.get("/admin/imports/delete")
    assert response.status_code == 200
    assert f'value="{CITY}" required disabled' in response.text
    assert "Используется пользователями" in response.text
    assert "Удалить выбранный город</button>" not in response.text


def test_explicit_confirmation_is_required(admin_client, db_session, empty_city):
    response = admin_client.post(URL, data={"city": CITY, "csrf_token": CSRF})
    assert response.status_code == 400
    assert "Подтвердите удаление" in response.text
    assert CITY in get_all_cities(db_session)


@pytest.mark.parametrize("city", ["", "  ", "Несуществующий"])
def test_missing_or_unknown_city_does_not_delete_anything(
    admin_client, db_session, empty_city, city
):
    assert post_delete(admin_client, city=city).status_code == 400
    assert CITY in get_all_cities(db_session)


def test_csrf_required(admin_client, db_session, empty_city):
    response = admin_client.post(URL, data={"city": CITY, "confirm": "true"})
    assert response.status_code == 403
    assert CITY in get_all_cities(db_session)


def test_anonymous_cannot_delete(client, db_session, empty_city):
    response = post_delete(client, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"
    assert CITY in get_all_cities(db_session)


@pytest.mark.parametrize("role", ["user", "ambassador", "brand_ambassador"])
def test_non_admin_cannot_delete(client, db_session, empty_city, role):
    user = User(email="not-admin@test.local", role=role)
    db_session.add(user)
    db_session.flush()
    sid = new_session_id()
    db_session.add(SessionModel(id=sid, user_id=user.id, expires_at=default_expiry()))
    db_session.commit()
    client.cookies.set("session_id", sid)
    assert post_delete(client).status_code == 403
    assert CITY in get_all_cities(db_session)


def test_failed_commit_rolls_back_all_metadata(db_session, empty_city, monkeypatch):
    def fail_commit():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        delete_empty_city(db_session, CITY)
    assert db_session.query(EventLog).filter_by(city=CITY).count() == 1
    assert db_session.query(CityRegion).filter_by(city=CITY).count() == 1


def test_empty_city_list_refreshes_after_deleting_import(
    admin_client, db_session, empty_city
):
    db_session.add(Sale(city=CITY, qty=1))
    db_session.commit()
    assert not get_empty_cities(db_session)
    response = admin_client.post(
        "/admin/imports/delete/confirm", data={"city": CITY, "csrf_token": CSRF}
    )
    assert response.status_code == 200
    assert "Удалено строк: 1" in response.text
    assert f'value="{CITY}" required ' in response.text
    assert get_empty_cities(db_session)[0]["can_delete"]


def test_names_are_escaped_in_cleanup_list(admin_client, db_session):
    db_session.add(EventLog(city='<script>alert("city")</script>'))
    db_session.commit()
    response = admin_client.get("/admin/imports/delete")
    assert '<script>alert("city")</script>' not in response.text
    assert "&lt;script&gt;" in response.text
