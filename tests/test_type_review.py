"""Ревизия типов точек — детект клиентов с разными Sale.type от месяца к
месяцу + ручное выравнивание одним UPDATE."""

from conftest import CSRF_TOKEN


def _sale(db_session, city, client, sale_type, month, weight=10.0):
    from app.models import Sale

    s = Sale(
        city=city,
        month=month,
        type=sale_type,
        client=client,
        raw_name="Табак Х",
        raw_sku="X",
        qty=1,
        weight=weight,
        matched=False,
    )
    db_session.add(s)
    db_session.commit()
    return s


def test_no_drift_when_type_consistent(db_session):
    from app.services.type_review_service import (
        get_review_cities,
        get_type_drift_groups,
    )

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-08-01")

    assert get_type_drift_groups(db_session) == []
    assert get_review_cities(db_session) == []


def test_review_cities_only_include_actionable_drift(db_session):
    from app.services.type_review_service import get_review_cities, resync_client_type

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе А", None, "2026-08-01")
    _sale(db_session, "Ангарск", "Кафе Б", "Розница", "2026-07-01")
    _sale(db_session, "Братск", "Кафе В", None, "2026-07-01")
    _sale(db_session, "Братск", "Кафе В", "", "2026-08-01")

    assert get_review_cities(db_session) == ["Иркутск"]
    resync_client_type(db_session, "Иркутск", "Кафе А", "HoReCa")
    assert get_review_cities(db_session) == []


def test_drift_detected_and_default_is_majority(db_session):
    from app.services.type_review_service import get_type_drift_groups

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-05-01")
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-06-01")
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе А", "Розница", "2026-08-01")

    groups = get_type_drift_groups(db_session)
    assert len(groups) == 1
    g = groups[0]
    assert g["city"] == "Иркутск"
    assert g["client"] == "Кафе А"
    assert g["default_type"] == "HoReCa"  # 3 строки против 1
    assert g["total_rows"] == 4
    assert ("HoReCa", 3) in g["types"]
    assert ("Розница", 1) in g["types"]
    assert g["latest_month"] == "2026-08-01"
    assert g["latest_types"] == ["Розница"]


def test_review_filters_city_and_uses_chronological_month(db_session):
    from app.services.type_review_service import get_type_drift_groups

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "Декабрь 2025")
    _sale(db_session, "Иркутск", "Кафе А", "Розница", "2026-01-01")
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "Январь 2026")
    _sale(db_session, "Ангарск", "Кафе Б", "HoReCa", "2026-02-01")
    _sale(db_session, "Ангарск", "Кафе Б", "Розница", "2026-03-01")

    groups = get_type_drift_groups(db_session, city="Иркутск")
    assert len(groups) == 1
    assert groups[0]["client"] == "Кафе А"
    assert groups[0]["latest_month"] == "2026-01-01"
    assert groups[0]["latest_types"] == ["HoReCa", "Розница"]


def test_drift_ignores_client_with_single_type_even_if_null_present(db_session):
    """Если тип встречается всего в ДВУХ вариантах, но один из них — NULL
    (регион не прислал), это тоже дрейф — есть что выравнивать."""
    from app.services.type_review_service import get_type_drift_groups

    _sale(db_session, "Иркутск", "Кафе Б", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе Б", None, "2026-08-01")

    groups = get_type_drift_groups(db_session)
    assert len(groups) == 1
    g = groups[0]
    assert g["default_type"] == "HoReCa"
    assert g["type_options"] == [("HoReCa", 1)]  # NULL не предлагается на выбор
    assert (None, 1) in g["types"]  # но виден в разбивке
    assert g["latest_month"] == "2026-08-01"
    assert g["latest_types"] == [None]


def test_resync_client_type_updates_all_rows(db_session):
    from app.services.type_review_service import resync_client_type

    _sale(db_session, "Иркутск", "Кафе В", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе В", "Розница", "2026-08-01")
    _sale(db_session, "Иркутск", "Кафе В", None, "2026-09-01")
    _sale(db_session, "Иркутск", "Кафе Другое", "Розница", "2026-08-01")  # не трогаем

    n = resync_client_type(db_session, "Иркутск", "Кафе В", "HoReCa")
    assert n == 2  # Розница + NULL, HoReCa уже была

    from app.models import Sale

    db_session.expire_all()
    types = {
        s.type for s in db_session.query(Sale).filter(Sale.client == "Кафе В").all()
    }
    assert types == {"HoReCa"}

    other = db_session.query(Sale).filter(Sale.client == "Кафе Другое").first()
    assert other.type == "Розница"  # соседний клиент не задет


def test_type_review_page_and_resync_route(admin_client, db_session):
    _sale(db_session, "Иркутск", "Кафе Г", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе Г", "Розница", "2026-08-01")
    _sale(db_session, "Ангарск", "Кафе Д", "HoReCa", "2026-07-01")
    _sale(db_session, "Ангарск", "Кафе Д", "Розница", "2026-08-01")

    resp = admin_client.get("/admin/point-types/review?city=Иркутск")
    assert resp.status_code == 200
    assert "Кафе Г" in resp.text
    assert "Кафе Д" not in resp.text
    assert "HoReCa" in resp.text
    assert "Розница" in resp.text
    assert "Август 2026" in resp.text
    assert "Тип в последнем месяце продаж" in resp.text

    resp = admin_client.post(
        "/admin/point-types/review/resync",
        data={
            "csrf_token": CSRF_TOKEN,
            "city": "Иркутск",
            "client": "Кафе Г",
            "correct_type": "HoReCa",
            "filter_city": "Иркутск",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA" in resp.headers["location"]

    from app.models import Sale

    db_session.expire_all()
    types = {
        s.type for s in db_session.query(Sale).filter(Sale.client == "Кафе Г").all()
    }
    assert types == {"HoReCa"}


def test_manual_type_assignment_applies_to_selected_city_and_client(
    admin_client, db_session
):
    from app.models import Sale

    _sale(db_session, "Иркутск", "Кафе А", "Кальянная", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе А", "Кальянная", "2026-08-01")
    _sale(db_session, "Ангарск", "Кафе А", "Кальянная", "2026-07-01")
    _sale(db_session, "Ангарск", "Кафе Б", "Кальянная", "2026-07-01")
    url = "/admin/point-types/client"

    page = admin_client.get(url, params={"city": "Иркутск"})
    assert "Кафе А" in page.text
    assert "Кафе Б" not in page.text

    data = {"csrf_token": CSRF_TOKEN, "city": "Иркутск", "point_type": "Retail"}
    invalid = admin_client.post(url, data=data | {"client": "Кафе Б"})
    assert "Выберите клиента из этого города" in invalid.text

    saved = admin_client.post(
        url, data=data | {"client": "Кафе А"}, follow_redirects=False
    )
    assert saved.status_code == 303
    assert "updated=2" in saved.headers["location"]
    db_session.expire_all()
    sales = db_session.query(Sale).filter(Sale.client == "Кафе А").all()
    assert {(sale.city, sale.type) for sale in sales} == {
        ("Иркутск", "Retail"),
        ("Ангарск", "Кальянная"),
    }
    assert {sale.raw_point_type for sale in sales if sale.city == "Иркутск"} == {
        "Кальянная"
    }
