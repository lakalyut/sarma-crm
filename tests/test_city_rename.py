import pytest

from app.auth_models import SessionModel, User, default_expiry, new_session_id
from app.models import CityRegion, EventLog, Region, Sale, Visit
from app.services.cities_service import CITY_MODELS, get_all_cities, rename_city
from app.services.sales_options_service import get_cities

OLD = "Северный Кавказ"
NEW = "Пятигорск"
CSRF = "test-csrf-token"


@pytest.fixture
def city_data(db_session):
    user = User(email="city@test.local", role="ambassador", city=OLD)
    region = Region(name="Кавказ")
    db_session.add_all([user, region])
    db_session.flush()
    visit = Visit(ambassador_id=user.id, city=OLD, client="Кафе", sale_type="HoReCa")
    sale = Sale(city=OLD, client="Кафе", type="HoReCa", qty=10, month="2026-09-01")
    assignment = CityRegion(city=OLD, region_id=region.id)
    event = EventLog(city=OLD, rows_imported=1)
    other = Sale(city="Иркутск", client="Другая точка", qty=3)
    db_session.add_all([visit, sale, assignment, event, other])
    db_session.commit()
    return user, visit, sale, assignment, event, other


def post_rename(client, new_name=NEW, old_name=OLD, **kwargs):
    return client.post(
        "/admin/regions/rename-city",
        data={"old_name": old_name, "new_name": new_name, "csrf_token": CSRF},
        **kwargs,
    )


def test_rename_updates_all_links_and_preserves_records(
    admin_client, db_session, city_data
):
    user, visit, sale, assignment, event, other = city_data
    ids = [row.id for row in city_data]
    response = post_rename(admin_client, new_name="  Пятигорск  ")
    assert response.status_code == 200
    assert "Город переименован" in response.text
    for row in city_data:
        db_session.refresh(row)
    assert [row.id for row in city_data] == ids
    assert all(row.city == NEW for row in (user, visit, sale, assignment, event))
    assert other.city == "Иркутск"
    assert visit.ambassador_id == user.id
    assert sale.qty == 10
    assert assignment.region_id == db_session.query(Region).one().id
    assert OLD not in get_all_cities(db_session)
    assert NEW in get_cities(db_session)


@pytest.mark.parametrize(
    "new_name", ["", "   ", OLD, "ИРКУТСК", "a" * 201, "Город\nновый"]
)
def test_invalid_name_does_not_change_data(
    admin_client, db_session, city_data, new_name
):
    response = post_rename(admin_client, new_name=new_name)
    assert response.status_code == 400
    assert 'role="alert"' in response.text
    assert db_session.query(Sale).filter(Sale.city == OLD).count() == 1
    assert db_session.query(User).filter(User.city == OLD).count() == 1


def test_unknown_source_is_rejected(admin_client, db_session, city_data):
    response = post_rename(admin_client, old_name="Несуществующий")
    assert response.status_code == 400
    assert "Город не найден" in response.text
    assert NEW not in get_all_cities(db_session)


def test_collision_with_city_only_in_profiles_is_rejected(
    admin_client, db_session, city_data
):
    db_session.add(User(email="another@test.local", city=NEW))
    db_session.commit()
    response = post_rename(admin_client)
    assert response.status_code == 400
    assert "уже существует" in response.text
    assert db_session.query(CityRegion).one().city == OLD


def test_rename_available_without_sales_or_regions(admin_client, db_session):
    user = User(email="no-sales@test.local", city=OLD)
    db_session.add(user)
    db_session.commit()
    page = admin_client.get("/admin/regions")
    assert f'value="{OLD}"' in page.text
    assert post_rename(admin_client).status_code == 200
    db_session.refresh(user)
    assert user.city == NEW


def test_failed_commit_rolls_back_every_table(db_session, city_data, monkeypatch):
    def fail_commit():
        raise RuntimeError("commit failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="commit failure"):
        rename_city(db_session, OLD, NEW)
    for model in CITY_MODELS:
        assert db_session.query(model).filter(model.city == OLD).count() == 1
        assert db_session.query(model).filter(model.city == NEW).count() == 0


def test_non_admin_cannot_rename(client, db_session, city_data):
    user = User(email="viewer@test.local", role="user")
    db_session.add(user)
    db_session.flush()
    session_id = new_session_id()
    db_session.add(
        SessionModel(id=session_id, user_id=user.id, expires_at=default_expiry())
    )
    db_session.commit()
    client.cookies.set("session_id", session_id)
    response = post_rename(client, follow_redirects=False)
    assert response.status_code == 403
    assert db_session.query(Sale).filter(Sale.city == OLD).count() == 1


def test_rename_requires_csrf(admin_client, db_session, city_data):
    response = admin_client.post(
        "/admin/regions/rename-city", data={"old_name": OLD, "new_name": NEW}
    )
    assert response.status_code == 403
    assert OLD in get_all_cities(db_session)
