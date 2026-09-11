"""«Здоровье клиентской базы» — статус клиента целиком (не по SKU):
активен/новый/нестабильный/потерян. (Было 6 статусов, слиты в 4 по фидбеку
пользователя — см. докстринг client_health_service.py.)"""

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

    status, _, _ = detect_client_status([1, 1, 1, 1], DEFAULT_SETTINGS)
    assert status == "existing"


def test_detect_client_status_new():
    from app.services.client_health_service import detect_client_status

    status, _, _ = detect_client_status([0, 0, 0, 1], DEFAULT_SETTINGS)
    assert status == "new"


def test_detect_client_status_ignores_months_before_first_sale():
    """Регресс (репорт 2026-09-11): точка открылась в середине общей истории
    города («весь загруженный период») и с тех пор продаёт каждый месяц без
    единого реального пропуска — месяцы ДО открытия не должны считаться
    разрывом в её закупках."""
    from app.services.client_health_service import detect_client_status

    months_data = [0, 0, 0, 0, 0, 0, 5, 5, 5, 5]
    status, _, details = detect_client_status(months_data, DEFAULT_SETTINGS)
    assert status == "existing"
    assert details["max_gap_inside"] == 0

    # но настоящий разрыв ПОСЛЕ открытия по-прежнему ловится
    months_data_with_real_gap = [0, 0, 0, 0, 0, 0, 5, 0, 0, 5]
    status2, _, details2 = detect_client_status(
        months_data_with_real_gap, DEFAULT_SETTINGS
    )
    assert status2 == "unstable"
    assert details2["max_gap_inside"] == 2


def test_detect_client_status_lost():
    from app.services.client_health_service import detect_client_status

    status, _, _ = detect_client_status([1, 1, 0, 0], DEFAULT_SETTINGS)
    assert status == "lost"


def test_detect_client_status_unstable_trailing_gap():
    """Хвостовой разрыв есть, но короче lost_months — ранний сигнал,
    ещё не «Потерян» (было бы «Замедляется» до слияния статусов)."""
    from app.services.client_health_service import detect_client_status

    status, _, _ = detect_client_status([1, 1, 1, 0], DEFAULT_SETTINGS)
    assert status == "unstable"


def test_detect_client_status_unstable_internal_gap():
    from app.services.client_health_service import detect_client_status

    status, _, _ = detect_client_status([1, 0, 1, 1], DEFAULT_SETTINGS)
    assert status == "unstable"


def test_detect_client_status_unstable_after_long_dropout():
    """Разрыв внутри периода длиной lost_months и больше, но к концу окна
    клиент снова активен (было бы «Вернулся» до слияния статусов) — тоже
    «Нестабильный», причина уточняется в тексте подсказки, не в статусе."""
    from app.services.client_health_service import detect_client_status

    status, _, _ = detect_client_status([1, 0, 0, 1], DEFAULT_SETTINGS)
    assert status == "unstable"


def test_detect_client_status_empty():
    from app.services.client_health_service import detect_client_status

    status, _, _ = detect_client_status([0, 0, 0, 0], DEFAULT_SETTINGS)
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


def test_build_client_health_new_point_mid_history_is_active(db_session):
    """Сквозной регресс (не только на голой функции): в городе есть долгая
    история (другой клиент торгует с января), «Кафе Новое» открылось в июне
    и с тех пор продаёт каждый месяц без пропусков — статус должен быть
    «Активен», а не «Нестабильный» из-за месяцев до открытия."""
    from app.services.client_health_service import build_client_health

    for month in ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]:
        _sale(db_session, "Кафе Старое", "HoReCa", month)

    for month in ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]:
        _sale(db_session, "Кафе Новое", "HoReCa", month)

    months = [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
        "2026-04-01",
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
        "2026-08-01",
        "2026-09-01",
    ]
    health = build_client_health(db_session, city="Иркутск", selected_months=months)
    by_client = {r["client"]: r for r in health["rows"]}

    assert by_client["Кафе Новое"]["status"] == "existing"


def test_status_reason_mentions_gap_and_last_month(db_session):
    """Причина статуса — то, что уходит в title-тултип на плашке — должна
    называть конкретный месяц/длину перерыва, а не быть общей фразой."""
    from app.services.client_health_service import build_client_health

    _sale(db_session, "Кафе Перерыв", "HoReCa", "2026-06-01")
    _sale(db_session, "Кафе Перерыв", "HoReCa", "2026-09-01")

    months = ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]
    health = build_client_health(db_session, city="Иркутск", selected_months=months)
    row = health["rows"][0]

    assert row["status"] == "unstable"
    assert "Июль 2026" in row["status_reason"]
    assert "Август 2026" in row["status_reason"]
    assert "2 мес." in row["status_reason"]


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
    # у города есть продажи и в августе, и в сентябре (от другого клиента) —
    # иначе get_months() вообще не знает про эти месяцы, и «Кафе Потеряшка»
    # классифицируется в единственном известном месяце (июль) как «Активен»,
    # а не «Потерян».
    _sale(db_session, "Кафе Другое", "HoReCa", "2026-08-01")
    _sale(db_session, "Кафе Другое", "HoReCa", "2026-09-01")

    resp = admin_client.get(
        "/analytics/client-analysis?tab=client_health"
        "&city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
        "&months=2026-07-01&months=2026-08-01&months=2026-09-01"
    )
    assert resp.status_code == 200
    assert "Здоровье базы" in resp.text
    assert "Кафе Потеряшка" in resp.text
    assert 'data-status="lost"' in resp.text
    assert 'title="Нет продаж' in resp.text


def test_clients_summary_shows_status_badge(admin_client, db_session):
    _sale(db_session, "Кафе Значок", "HoReCa", "2026-09-01")

    resp = admin_client.get(
        "/analytics/clients?city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
    )
    assert resp.status_code == 200
    assert "Кафе Значок" in resp.text
    assert "client-status-badge" in resp.text
    # единственный доступный месяц в городе — статус "Активен" (не с чего
    # отсчитывать "новый"), причина — во всплывающей подсказке title=...
    assert 'title="Стабильные продажи' in resp.text
    # колонка сортируется кликом на заголовок — data-sort="status_rank" на
    # <th> и одноимённый data-status_rank на строке (existing = ранг из
    # STATUS_ORDER, не текст статуса)
    assert 'data-sort="status_rank"' in resp.text
    assert 'data-status_rank="' in resp.text
