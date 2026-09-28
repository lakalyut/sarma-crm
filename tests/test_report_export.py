"""Скачивание отчётов в HTML: «Амбассадорский отчёт» и «Представленность SKU»
(запрос 2026-09-28). Выгрузка — автономный файл: стили/скрипты вшиты, ссылок на
приложение нет."""

from urllib.parse import quote

CITY = "Иркутск"
CITY_QS = quote(CITY)


def _sale(db_session, client, sale_type, sku, month="2026-09-01", qty=3):
    from app.models import Sale

    db_session.add(
        Sale(
            city=CITY,
            month=month,
            type=sale_type,
            client=client,
            sku=sku,
            raw_sku=sku,
            qty=qty,
            weight=qty * 10,
            matched=False,
        )
    )
    db_session.commit()


def _seed(db_session):
    _sale(db_session, "Кафе Экспорт", "HoReCa", "EXP-1", month="2026-08-01")
    _sale(db_session, "Кафе Экспорт", "HoReCa", "EXP-1", month="2026-09-01")
    _sale(db_session, "Кафе Экспорт", "HoReCa", "EXP-2", month="2026-09-01")


AMB_URL = (
    f"/analytics/client-analysis?tab=ambassadors&city={CITY_QS}"
    "&clients=" + quote("Кафе Экспорт") + "&months=2026-08-01&months=2026-09-01"
)
SP_URL = (
    f"/analytics/client-analysis?tab=sku_presence&city={CITY_QS}"
    "&months=2026-09-01&skus=EXP-1&skus=EXP-2"
)


def _assert_standalone(resp):
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "filename*=UTF-8''" in disposition
    body = resp.text
    # автономность: стили вшиты, внешних подключений и ссылок в приложение нет
    assert "<style>" in body and ".amb-card" in body
    assert '<link rel="stylesheet"' not in body
    assert "<form" not in body
    assert 'href="/' not in body
    assert 'src="/' not in body


def test_ambassadors_page_has_download_link(admin_client, db_session):
    _seed(db_session)
    resp = admin_client.get(AMB_URL)
    assert resp.status_code == 200
    assert "Скачать HTML" in resp.text
    assert "download=1" in resp.text
    assert "content-disposition" not in resp.headers


def test_ambassadors_download_is_standalone_html(admin_client, db_session):
    _seed(db_session)
    resp = admin_client.get(AMB_URL + "&download=1")

    _assert_standalone(resp)
    body = resp.text
    assert "Амбассадорский отчёт" in body
    assert "Кафе Экспорт" in body
    assert "EXP-1" in body and "EXP-2" in body
    # карточка раскрыта и интерактивна без сервера: скрипты вшиты
    assert "amb-sku-details is-hidden" not in body
    assert "initSortableSkuTable" in body
    # кнопок сворачивания нет (текст «Показать SKU» остаётся только в вшитом JS)
    assert 'class="amb-toggle"' not in body
    assert 'class="amb-link-toggle"' not in body
    assert "Скачать HTML" not in body


def test_ambassadors_download_without_results_falls_back_to_page(
    admin_client, db_session
):
    resp = admin_client.get(
        f"/analytics/client-analysis?tab=ambassadors&city={CITY_QS}&download=1"
    )
    assert resp.status_code == 200
    assert "content-disposition" not in resp.headers
    assert "Выбери регион, клиентов и месяцы" in resp.text


def test_sku_presence_page_has_download_link(admin_client, db_session):
    _seed(db_session)
    resp = admin_client.get(SP_URL)
    assert resp.status_code == 200
    assert "Скачать HTML" in resp.text
    assert "download=1" in resp.text
    assert "content-disposition" not in resp.headers


def test_sku_presence_download_is_standalone_html(admin_client, db_session):
    _seed(db_session)
    resp = admin_client.get(SP_URL + "&count_from=2&count_to=2&download=1")

    _assert_standalone(resp)
    body = resp.text
    assert "Представленность SKU" in body
    assert "Кафе Экспорт" in body
    assert "EXP-1 · " in body
    assert "от 2 до 2" in body
    assert "Скачать HTML" not in body


def test_sku_presence_download_respects_filters(admin_client, db_session):
    _seed(db_session)
    _sale(db_session, "Кафе Одна Позиция", "HoReCa", "EXP-1")

    resp = admin_client.get(SP_URL + "&count_from=2&download=1")
    assert resp.status_code == 200
    assert "Кафе Экспорт" in resp.text
    assert "Кафе Одна Позиция" not in resp.text


def test_download_requires_login(client, db_session):
    _seed(db_session)
    resp = client.get(SP_URL + "&download=1", follow_redirects=False)
    assert resp.status_code in (302, 303, 401, 403)
    assert "content-disposition" not in resp.headers
