"""«Здоровье клиентской базы» — статус клиента целиком (не по SKU):
активен/новый/потерян/замедляется/нестабильный/вернулся."""

DEFAULT_SETTINGS = {
    "new_client_months": 2,
    "lost_months": 2,
    "unstable_gap_months": 1,
}


def _sale(db_session, client, sale_type, month, weight=10.0, city="Иркутск"):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month=month,
            type=sale_type,
            client=client,
            sku="S-1",
            raw_sku="S-1",
            qty=1,
            weight=weight,
            matched=False,
        )
    )
    db_session.commit()


def test_detect_client_status_existing():
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([1, 1, 1, 1], DEFAULT_SETTINGS)
    assert status == "existing"


def test_detect_client_status_new():
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([0, 0, 0, 1], DEFAULT_SETTINGS)
    assert status == "new"


def test_detect_client_status_lost():
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([1, 1, 0, 0], DEFAULT_SETTINGS)
    assert status == "lost"


def test_detect_client_status_slowing():
    """Хвостовой разрыв есть, но короче lost_months — ранний сигнал,
    ещё не «Потерян»."""
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([1, 1, 1, 0], DEFAULT_SETTINGS)
    assert status == "slowing"


def test_detect_client_status_unstable():
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([1, 0, 1, 1], DEFAULT_SETTINGS)
    assert status == "unstable"


def test_detect_client_status_winback():
    """Разрыв внутри периода длиной lost_months и больше, но к концу окна
    клиент снова активен — вернулся после ухода."""
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([1, 0, 0, 1], DEFAULT_SETTINGS)
    assert status == "winback"


def test_detect_client_status_empty():
    from app.services.client_health_service import detect_client_status

    status, _ = detect_client_status([0, 0, 0, 0], DEFAULT_SETTINGS)
    assert status == "empty"


def test_build_client_health_groups_by_client_and_type(db_session):
    from app.services.client_health_service import build_client_health

    _sale(db_session, "Кафе А", "HoReCa", "2026-07-01")
    _sale(db_session, "Кафе А", "HoReCa", "2026-08-01")
    _sale(db_session, "Кафе А", "HoReCa", "2026-09-01")
    _sale(db_session, "Кафе А", "Розница", "2026-09-01")  # другой тип точки

    months = ["2026-07-01", "2026-08-01", "2026-09-01"]
    health = build_client_health(db_session, city="Иркутск", selected_months=months)

    by_key = {(r["client"], r["sale_type"]): r for r in health["rows"]}
    assert by_key[("Кафе А", "HoReCa")]["status"] == "existing"
    assert by_key[("Кафе А", "HoReCa")]["weight_total"] == 30.0
    assert by_key[("Кафе А", "Розница")]["status"] == "new"
    assert health["status_counts"]["existing"] == 1
    assert health["status_counts"]["new"] == 1


def test_build_client_health_empty_without_city_or_months(db_session):
    from app.services.client_health_service import build_client_health

    assert (
        build_client_health(db_session, city="", selected_months=["2026-09-01"])["rows"]
        == []
    )
    assert (
        build_client_health(db_session, city="Иркутск", selected_months=[])["rows"]
        == []
    )


def test_client_health_tab_renders(admin_client, db_session):
    _sale(db_session, "Кафе Потеряшка", "HoReCa", "2026-07-01")

    resp = admin_client.get(
        "/analytics/client-analysis?tab=client_health"
        "&city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
        "&months=2026-07-01&months=2026-08-01&months=2026-09-01"
    )
    assert resp.status_code == 200
    assert "Здоровье базы" in resp.text
    assert "Кафе Потеряшка" in resp.text
    assert "Потерян" in resp.text


def test_clients_summary_shows_status_badge(admin_client, db_session):
    _sale(db_session, "Кафе Значок", "HoReCa", "2026-09-01")

    resp = admin_client.get(
        "/analytics/clients?city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
    )
    assert resp.status_code == 200
    assert "Кафе Значок" in resp.text
    assert "client-status-badge" in resp.text
