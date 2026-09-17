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


def _make_analyst(db_session, telegram_id=888333, first_name="Ана"):
    from app.auth_models import User

    user = User(
        email="clients-user@example.com",
        role="user",
        is_active=True,
        telegram_id=telegram_id,
        first_name=first_name,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_ambassador_ignores_city_query_param(db_session, client):
    """Амбассадор — город всегда user.city, ?city= из query игнорируется
    (тот принцип, что и раньше, до расширения доступа на роль user)."""
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    _sale(db_session, "Новосибирск", "Кафе Б", "HoReCa", sku="S-2", name="Табак Б")
    ambassador = _make_ambassador(db_session, "Иркутск")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/clients?city=" + "Новосибирск",
        headers={"Authorization": f"tma {init_data}"},
    )
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["client"] == "Кафе А"  # не Новосибирск, а свой город


def test_user_role_clients_empty_without_city(db_session, client):
    """Роль user (запрос 2026-09-16) без своего города — без явного
    ?city= пустой список, не 500 и не чужие данные по умолчанию."""
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    analyst = _make_analyst(db_session)

    init_data = signed_init_data(analyst.telegram_id)
    resp = client.get(
        "/ambassador/app/clients",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert resp.status_code == 200
    assert resp.json()["rows"] == []


def test_user_role_clients_uses_query_city(db_session, client):
    """С явным ?city= роль user видит любой город — не зафиксирована на
    одном, в отличие от ambassador."""
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    _sale(db_session, "Новосибирск", "Кафе Б", "HoReCa", sku="S-2", name="Табак Б")
    analyst = _make_analyst(db_session)

    init_data = signed_init_data(analyst.telegram_id)

    resp_a = client.get(
        "/ambassador/app/clients?city=Иркутск",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert [r["client"] for r in resp_a.json()["rows"]] == ["Кафе А"]

    resp_b = client.get(
        "/ambassador/app/clients?city=Новосибирск",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert [r["client"] for r in resp_b.json()["rows"]] == ["Кафе Б"]


def test_user_role_client_detail_uses_query_city(db_session, client):
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
    analyst = _make_analyst(db_session)

    init_data = signed_init_data(analyst.telegram_id)
    resp = client.get(
        "/ambassador/app/client-detail"
        "?client=%D0%9A%D0%B0%D1%84%D0%B5%20%D0%90&sale_type=HoReCa&city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["total_weight"] == 10.0


def test_user_role_client_detail_empty_without_city(db_session, client):
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    analyst = _make_analyst(db_session)

    init_data = signed_init_data(analyst.telegram_id)
    resp = client.get(
        "/ambassador/app/client-detail?client=%D0%9A%D0%B0%D1%84%D0%B5%20%D0%90&sale_type=HoReCa",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] is None
    assert body["rows"] == []


def test_user_role_options_returns_all_cities(db_session, client):
    """«Визит» — полноценная вкладка и для роли user (запрос 2026-09-17,
    «полный мини-ап, но визиты никуда не уходят»): options отдаёт ВСЕ
    города сразу (не один, как амбассадору), форма визита сама даёт
    выбрать."""
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    _sale(db_session, "Новосибирск", "Кафе Б", "Розница", sku="S-2", name="Табак Б")
    analyst = _make_analyst(db_session)

    init_data = signed_init_data(analyst.telegram_id)
    resp = client.get(
        "/ambassador/app/options",
        headers={"Authorization": f"tma {init_data}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["cities"]) == {"Иркутск", "Новосибирск"}
    assert body["clients_by_city"]["Иркутск"] == ["Кафе А"]
    assert body["clients_by_city"]["Новосибирск"] == ["Кафе Б"]


def test_user_role_visit_is_demo_not_persisted(db_session, client):
    """Визит роли user проходит полную валидацию, но НЕ пишется в БД —
    «для демонстрации функционала», «не засорять БД» (запрос 2026-09-17)."""
    from app.models import Product, Visit

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    product = Product(
        category="Табак",
        brand="Сарма",
        flavor="Мята",
        canonical_sku="DEMO-SKU",
        canonical_name="Сарма Мята",
        norm_brand="сарма",
        norm_flavor="мята",
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    analyst = _make_analyst(db_session)
    init_data = signed_init_data(analyst.telegram_id)

    resp = client.post(
        "/ambassador/app/visits",
        headers={"Authorization": f"tma {init_data}"},
        json={
            "city": "Иркутск",
            "client": "Кафе А",
            "sale_type": "HoReCa",
            "product_ids": [product.id],
            "sku_classic": "1",
            "sku_strong": "1",
            "sku_light": "1",
            "people_count": "5",
            "comment": "демо",
            "goal": "демо",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["demo"] is True
    assert body["visit_id"] is None
    assert db_session.query(Visit).count() == 0


def test_user_role_visit_still_validated(db_session, client):
    """Демо-режим не отключает валидацию — несуществующий клиент всё
    равно отклоняется с 400."""
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    analyst = _make_analyst(db_session)
    init_data = signed_init_data(analyst.telegram_id)

    resp = client.post(
        "/ambassador/app/visits",
        headers={"Authorization": f"tma {init_data}"},
        json={"city": "Иркутск", "client": "Несуществующий", "sale_type": "HoReCa"},
    )
    assert resp.status_code == 400


def test_ambassador_visit_still_persisted(db_session, client):
    """Контроль: у ambassador визит по-прежнему настоящий (dry_run не
    затронул основной путь)."""
    from app.models import Product, Visit

    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    product = Product(
        category="Табак",
        brand="Сарма",
        flavor="Мята",
        canonical_sku="AMB-SKU",
        canonical_name="Сарма Мята",
        norm_brand="сарма",
        norm_flavor="мята",
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    ambassador = _make_ambassador(db_session, "Иркутск")
    init_data = signed_init_data(ambassador.telegram_id)

    resp = client.post(
        "/ambassador/app/visits",
        headers={"Authorization": f"tma {init_data}"},
        json={
            "city": "Иркутск",
            "client": "Кафе А",
            "sale_type": "HoReCa",
            "product_ids": [product.id],
            "sku_classic": "1",
            "sku_strong": "1",
            "sku_light": "1",
            "people_count": "5",
            "comment": "настоящий визит",
            "goal": "проверка",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["demo"] is False
    assert body["visit_id"] is not None
    assert db_session.query(Visit).count() == 1


def test_cities_endpoint_available_to_both_roles(db_session, client):
    _sale(db_session, "Иркутск", "Кафе А", "HoReCa", sku="S-1", name="Табак А")
    analyst = _make_analyst(db_session)
    ambassador = _make_ambassador(db_session, "Иркутск", telegram_id=888444)

    for user in (analyst, ambassador):
        init_data = signed_init_data(user.telegram_id)
        resp = client.get(
            "/ambassador/app/cities",
            headers={"Authorization": f"tma {init_data}"},
        )
        assert resp.status_code == 200
        assert "Иркутск" in resp.json()["cities"]


def test_clients_endpoints_require_auth(client):
    """Без заголовка Authorization: tma — та же (уже существующая) картина,
    что у любого другого /ambassador/app/*-эндпоинта: get_current_ambassador
    поднимает HTTPException(401), а общий @app.exception_handler(401) в
    main.py превращает его в редирект на /auth/login, а не голый 401 —
    так уже вело себя всё остальное в мини-апе до этой фичи."""
    resp = client.get("/ambassador/app/clients", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"
