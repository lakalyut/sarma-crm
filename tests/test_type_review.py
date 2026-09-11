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
    from app.services.type_review_service import get_type_drift_groups

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-07-01")
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", "2026-08-01")

    assert get_type_drift_groups(db_session) == []


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

    resp = admin_client.get("/admin/point-types/review")
    assert resp.status_code == 200
    assert "Кафе Г" in resp.text
    assert "HoReCa" in resp.text
    assert "Розница" in resp.text

    resp = admin_client.post(
        "/admin/point-types/review/resync",
        data={
            "csrf_token": CSRF_TOKEN,
            "city": "Иркутск",
            "client": "Кафе Г",
            "correct_type": "HoReCa",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    from app.models import Sale

    db_session.expire_all()
    types = {
        s.type for s in db_session.query(Sale).filter(Sale.client == "Кафе Г").all()
    }
    assert types == {"HoReCa"}
