"""Мини-ап (Telegram) — вкладка «Клиенты» (запрос пользователя, 2026-09-12):
браузерный путь амбассадора уже видел «Клиенты»/детализацию клиента по
своему городу (require_client_viewer, /analytics/clients), в мини-апе такого
не было вовсе — мини-ап аутентифицируется заголовком (Authorization: tma),
не cookie-сессией, обычные аналитические роуты ему недоступны. Тут —
отдельные JSON-эндпоинты с тем же принципом форса city=user.city."""

from conftest import signed_init_data


def _make_ambassador(db_session, city, telegram_id=888222):
    from app.auth_models import User

    user = User(
        email="clients-amb@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=telegram_id,
        first_name="Кли",
        last_name="Ентов",
        city=city,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _sale(db_session, city, client, sale_type, sku=None, name=None, qty=1, weight=5):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month="2026-01-01",
            type=sale_type,
            client=client,
            sku=sku,
            name=name,
            qty=qty,
            weight=weight,
            matched=sku is not None,
        )
    )
    db_session.commit()


def test_clients_list_scoped_to_ambassador_city(db_session, client):
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    _sale(db_session, "Новосибирск", "Кафе Чужой", "HoReCa", sku="S-2", name="Табак Б")
    ambassador = _make_ambassador(db_session, "Иркутск")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/clients",
        headers={"Authorization": f"tma {init_data}"},
    )

    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["client"] == "Кафе А"
    assert rows[0]["sale_type"] == "HoReCa"
    assert rows[0]["weight"] == 5.0


def test_clients_list_groups_by_type(db_session, client):
    _sale(db_session, "Иркутск", "Сеть Х", "HoReCa", sku="S-1", name="Табак А")
    _sale(db_session, "Иркутск", "Сеть Х", "Розница", sku="S-1", name="Табак А")
    ambassador = _make_ambassador(db_session, "Иркутск")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/clients",
        headers={"Authorization": f"tma {init_data}"},
    )

    rows = resp.json()["rows"]
    pairs = {(r["client"], r["sale_type"]) for r in rows}
    assert ("Сеть Х", "HoReCa") in pairs
    assert ("Сеть Х", "Розница") in pairs


def test_client_detail_returns_summary_and_rows(db_session, client):
    _sale(
        db_session,
        "Иркутск",
        "Кафе А",
        "HoReCa",
        sku="S-1",
        name="Табак Мята",
        qty=2,
        weight=10,
    )
    ambassador = _make_ambassador(db_session, "Иркутск")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/client-detail"
        "?client=%D0%9A%D0%B0%D1%84%D0%B5%20%D0%90&sale_type=HoReCa",
        headers={"Authorization": f"tma {init_data}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_weight"] == 10.0
    assert body["summary"]["unique_sku"] == 1
    assert len(body["rows"]) == 1
    assert body["rows"][0]["name"] == "Табак Мята"
    assert body["rows"][0]["qty"] == 2.0


def test_client_detail_empty_for_wrong_city(db_session, client):
    """Клиент реально есть, но в ЧУЖОМ городе — city всегда берётся из
    user.city, не из query, поэтому амбассадор не может подсмотреть чужой
    город, даже зная точное имя клиента."""
    _sale(db_session, "Новосибирск", "Кафе Чужой", "HoReCa", sku="S-1", name="Табак А")
    ambassador = _make_ambassador(db_session, "Иркутск")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/client-detail"
        "?client=%D0%9A%D0%B0%D1%84%D0%B5%20%D0%A7%D1%83%D0%B6%D0%BE%D0%B9&sale_type=HoReCa",
        headers={"Authorization": f"tma {init_data}"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] is None
    assert body["rows"] == []


def test_clients_endpoints_require_auth(client):
    """Без заголовка Authorization: tma — та же (уже существующая) картина,
    что у любого другого /ambassador/app/*-эндпоинта: get_current_ambassador
    поднимает HTTPException(401), а общий @app.exception_handler(401) в
    main.py превращает его в редирект на /auth/login, а не голый 401 —
    так уже вело себя всё остальное в мини-апе до этой фичи."""
    resp = client.get("/ambassador/app/clients", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"
