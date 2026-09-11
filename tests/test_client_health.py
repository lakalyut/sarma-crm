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


def test_detect_client_status_is_new_override():
    """`is_new=True` явно переданный извне (так делает build_client_health,
    см. регресс ниже) перебивает позиционный расчёт по самому окну —
    даже когда первая продажа в 1-й позиции массива (то, что раньше
    ГАРАНТИРОВАННО означало «не новый»)."""
    from app.services.client_health_service import detect_client_status

    # первая позиция активна — без override никогда не «Новый»
    status_default, _, _ = detect_client_status([5, 5], DEFAULT_SETTINGS)
    assert status_default == "existing"

    status_forced, _, _ = detect_client_status([5, 5], DEFAULT_SETTINGS, is_new=True)
    assert status_forced == "new"


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


def test_build_client_health_new_checked_against_full_history_not_window(db_session):
    """Регресс (запрос пользователя, 2026-09-11: «для новых — надо проверять
    весь период, был ли он до этого»). Окно — август-сентябрь (2 месяца,
    как раз new_client_months). У города есть более ранняя история
    («Кафе Старое» продаёт с января) — «Кафе Августовское» впервые продало
    именно в августе, первом месяце ЭТОГО окна. По старой (window-only)
    логике первая продажа в 1-й позиции массива никогда не «Новый» — а тут
    клиент буквально только что появился. build_client_health должен видеть
    это по полной истории города и всё равно поставить «Новый»."""
    from app.services.client_health_service import build_client_health

    for month in [
        "2026-01-01",
        "2026-02-01",
        "2026-03-01",
        "2026-04-01",
        "2026-05-01",
        "2026-06-01",
        "2026-07-01",
    ]:
        _sale(db_session, "Кафе Старое", "HoReCa", month)

    _sale(db_session, "Кафе Августовское", "HoReCa", "2026-08-01")
    _sale(db_session, "Кафе Августовское", "HoReCa", "2026-09-01")

    window = ["2026-08-01", "2026-09-01"]
    health = build_client_health(db_session, city="Иркутск", selected_months=window)
    by_client = {r["client"]: r for r in health["rows"]}

    assert by_client["Кафе Августовское"]["status"] == "new"
    assert "Август 2026" in by_client["Кафе Августовское"]["status_reason"]


def test_build_client_health_marks_silent_known_client_as_lost(db_session):
    """Регресс (запрос пользователя, 2026-09-11): статус теперь может
    считаться за короткое окно (квартал), не за всю историю. Клиент,
    покупавший только ДО этого окна (в городе он точно известен), не должен
    просто пропасть из выдачи с пустой плашкой — это однозначно «Потерян»,
    не «нет данных»."""
    from app.services.client_health_service import build_client_health

    _sale(db_session, "Кафе Давно", "HoReCa", "2026-01-01")
    _sale(db_session, "Кафе Давно", "HoReCa", "2026-02-01")
    # у города есть продажи и в окне (от другого клиента), иначе сами месяцы
    # окна не «существуют» для параметра selected_months в этом тесте
    _sale(db_session, "Кафе Свежее", "HoReCa", "2026-08-01")
    _sale(db_session, "Кафе Свежее", "HoReCa", "2026-09-01")

    quarter = ["2026-07-01", "2026-08-01", "2026-09-01"]
    health = build_client_health(db_session, city="Иркутск", selected_months=quarter)
    by_client = {r["client"]: r for r in health["rows"]}

    assert by_client["Кафе Давно"]["status"] == "lost"
    assert by_client["Кафе Давно"]["weight_total"] == 0.0
    assert (
        by_client["Кафе Давно"]["status_reason"]
        == "Нет продаж за весь выбранный период"
    )


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


def test_clients_summary_status_follows_months_filter(admin_client, db_session):
    """Явно выбранный в фильтре «Месяцы» период — статус считается по нему,
    не по умолчанию (квартал) и не по всей истории (запрос пользователя,
    2026-09-11)."""
    _sale(db_session, "Кафе Фильтр", "HoReCa", "2026-01-01")
    _sale(db_session, "Кафе Фильтр", "HoReCa", "2026-02-01")
    _sale(db_session, "Кафе Другое", "HoReCa", "2026-09-01")

    resp = admin_client.get(
        "/analytics/clients?city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
        "&months=2026-01-01&months=2026-02-01"
    )
    assert resp.status_code == 200
    assert "client-status-badge-existing" in resp.text
    assert "client-status-badge-lost" not in resp.text


def test_clients_summary_default_quarter_marks_old_client_lost(
    admin_client, db_session
):
    """Без явного фильтра статус по умолчанию считается за последний квартал
    (не за всю историю) — клиент, продававший только задолго до него, должен
    показать «Потерян», а не пропасть с пустой плашкой «—»."""
    _sale(db_session, "Кафе Давнее", "HoReCa", "2026-01-01")
    # заполняем город продажами вплоть до сентября (от другого клиента),
    # чтобы «последний квартал» (июль-сентябрь) реально не включал январь
    for month in ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]:
        _sale(db_session, "Кафе Свежее", "HoReCa", month)

    resp = admin_client.get(
        "/analytics/clients?city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
    )
    assert resp.status_code == 200
    assert "Кафе Давнее" in resp.text
    assert "client-status-badge-lost" in resp.text


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


def test_client_analysis_health_tab_removed(admin_client, db_session):
    """Вкладка «Здоровье базы» на «Анализе по клиентам» убрана (излишний
    функционал — запрос пользователя, 2026-09-11): статус клиента остаётся
    только колонкой на «Клиентах». ?tab=client_health больше не валидная
    вкладка — роут тихо откатывается на «Свод», не падает."""
    _sale(db_session, "Кафе Убрано", "HoReCa", "2026-09-01")

    resp = admin_client.get(
        "/analytics/client-analysis?tab=client_health"
        "&city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
    )
    assert resp.status_code == 200
    assert "Здоровье базы" not in resp.text
