from app.models import Sale

CSRF_TOKEN = "test-csrf-token"  # см. tests/conftest.py


def make_sale(db_session, city, month, sale_type, client="Клиент", **overrides):
    sale = Sale(
        city=city,
        month=month,
        type=sale_type,
        client=client,
        raw_name="Сырое название",
        raw_sku="RAW",
        qty=1.0,
        weight=0.1,
        matched=False,
        **overrides,
    )
    db_session.add(sale)
    db_session.commit()
    # id читаем сразу — дальше в тесте db_session может закоммититься ещё
    # раз (expire_on_commit по умолчанию True), а после HTTP-запроса строка
    # могла быть удалена другой сессией (get_db создаёт свою на запрос),
    # так что просроченный ORM-объект после этого не отрефрешится.
    return sale.id


def seed_mixed_sales(db_session):
    moscow_jan = make_sale(db_session, "Москва", "2026-01-01", "HoReCa")
    moscow_feb = make_sale(db_session, "Москва", "2026-02-01", "HoReCa")
    moscow_retail = make_sale(db_session, "Москва", "2026-01-01", "Розница")
    spb_jan = make_sale(db_session, "Санкт-Петербург", "2026-01-01", "HoReCa")
    return moscow_jan, moscow_feb, moscow_retail, spb_jan


def test_preview_without_filters_shows_error(admin_client, db_session):
    seed_mixed_sales(db_session)

    resp = admin_client.post(
        "/admin/imports/delete/preview", data={"csrf_token": CSRF_TOKEN}
    )

    assert resp.status_code == 200
    assert "Укажи хотя бы один фильтр" in resp.text
    assert db_session.query(Sale).count() == 4


def test_preview_counts_only_matching_rows(admin_client, db_session):
    seed_mixed_sales(db_session)

    resp = admin_client.post(
        "/admin/imports/delete/preview",
        data={"city": "Москва", "months": ["2026-01-01"], "csrf_token": CSRF_TOKEN},
    )

    assert resp.status_code == 200
    assert "Найдено строк для удаления: 2" in resp.text
    # предпросмотр ничего не удаляет
    assert db_session.query(Sale).count() == 4


def test_confirm_without_filters_is_rejected(admin_client, db_session):
    seed_mixed_sales(db_session)

    resp = admin_client.post(
        "/admin/imports/delete/confirm", data={"csrf_token": CSRF_TOKEN}
    )

    assert resp.status_code == 200
    assert "Удаление без фильтров запрещено" in resp.text
    assert db_session.query(Sale).count() == 4


def test_confirm_with_no_matches_reports_zero(admin_client, db_session):
    seed_mixed_sales(db_session)

    resp = admin_client.post(
        "/admin/imports/delete/confirm",
        data={"city": "Новосибирск", "csrf_token": CSRF_TOKEN},
    )

    assert resp.status_code == 200
    assert "ничего не найдено" in resp.text
    assert db_session.query(Sale).count() == 4


def test_confirm_deletes_only_matching_rows(admin_client, db_session):
    moscow_jan_id, moscow_feb_id, moscow_retail_id, spb_jan_id = seed_mixed_sales(
        db_session
    )

    resp = admin_client.post(
        "/admin/imports/delete/confirm",
        data={
            "city": "Москва",
            "months": ["2026-01-01"],
            "sale_type": "HoReCa",
            "csrf_token": CSRF_TOKEN,
        },
    )

    assert resp.status_code == 200
    assert "Удалено строк: 1" in resp.text

    db_session.expire_all()
    remaining_ids = {s.id for s in db_session.query(Sale).all()}
    assert moscow_jan_id not in remaining_ids
    assert remaining_ids == {moscow_feb_id, moscow_retail_id, spb_jan_id}


def test_delete_confirm_requires_admin(client, db_session):
    seed_mixed_sales(db_session)

    resp = client.post(
        "/admin/imports/delete/confirm",
        data={"city": "Москва", "csrf_token": CSRF_TOKEN},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"
    assert db_session.query(Sale).count() == 4
