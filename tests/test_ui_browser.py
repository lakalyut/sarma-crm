"""Браузерные регрессии общей формы и мобильных клиентов.

Отдельный запуск: RUN_BROWSER_TESTS=1 pytest -q tests/test_ui_browser.py.
Обычный pytest не требует установки браузера.
"""

import os
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Отдельный браузерный прогон"
)


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runner:
        instance = runner.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"),
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        yield instance
        instance.close()


@pytest.fixture()
def page(browser, admin_client, db_session):
    from app.models import Sale

    for city in ["Иркутск", "Москва", "Пятигорск"]:
        for name, sale_type, qty in [
            ("Клуб с длинным названием — Северный берег", "Кальянная", 10),
            ("Магазин Маяк", "Магазин", 100),
        ]:
            for i, month in enumerate(["2026-07-01", "2026-08-01", "2026-09-01"]):
                db_session.add(
                    Sale(
                        city=city,
                        month=month,
                        type=sale_type,
                        client=name,
                        sku="UI-1",
                        raw_sku="UI-1",
                        qty=qty * (i + 1),
                        weight=3 - i,
                        matched=False,
                    )
                )
    db_session.commit()
    context = browser.new_context(viewport={"width": 390, "height": 844})

    def handle(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != "pulse-ui.test":
            # Графики проверяются отдельно с настоящим Chart.js при визуальном QA.
            if "chart.js" in request.url:
                route.fulfill(
                    content_type="application/javascript",
                    body="window.Chart=function(){this.destroy=()=>{};this.update=()=>{};};",
                )
            else:
                route.abort()
            return
        response = admin_client.request(
            request.method,
            url.path + ("?" + url.query if url.query else ""),
            content=request.post_data_buffer,
            headers={
                k: v
                for k, v in request.headers.items()
                if k not in {"host", "cookie", "content-length"}
            },
            follow_redirects=False,
        )
        route.fulfill(
            status=response.status_code,
            headers={
                k: v
                for k, v in response.headers.items()
                if k not in {"content-length", "content-encoding", "set-cookie"}
            },
            body=response.content,
        )

    context.route("**/*", handle)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(
        "https://pulse-ui.test/analytics/clients?city=Иркутск"
        "&months=2026-07-01&months=2026-08-01&months=2026-09-01",
        wait_until="networkidle",
    )
    yield page
    context.close()
    assert not errors, errors


def test_custom_select_keyboard_sync_and_dynamic_options(page):
    page.locator(".clients-filter-panel > summary").click()
    display = page.locator("#field-matched + .custom-select-display")
    display.focus()
    page.keyboard.press("Enter")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert page.locator("#field-matched").input_value() == "1"
    assert display.get_attribute("aria-expanded") == "false"
    assert display.inner_text().strip() == "Да"
    # Смена значения извне отражается в отображаемом поле.
    page.evaluate(
        "const s=document.querySelector('#field-matched');"
        "s.value='0';s.dispatchEvent(new Event('change'));"
    )
    assert display.inner_text().strip() == "Нет"
    page.evaluate(
        "const s=document.querySelector('#field-matched');"
        "s.options[0].disabled=true;s.selectedIndex=1;"
        "s.dispatchEvent(new Event('change'));"
    )
    display.focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Home")
    page.keyboard.press("Enter")
    assert page.locator("#field-matched").input_value() == "1"
    page.evaluate("document.querySelector('#field-matched').disabled=true")
    page.wait_for_function(
        "document.querySelector('#field-matched + .custom-select-display').getAttribute('aria-disabled') === 'true'"
    )
    assert display.get_attribute("tabindex") == "-1"


def test_multiselect_keyboard_and_native_form_value(page):
    page.locator(".clients-filter-panel > summary").click()
    display = page.locator("#months-multiselect .multiselect-display")
    display.focus()
    page.keyboard.press("ArrowDown")
    assert display.get_attribute("aria-expanded") == "true"
    assert page.locator(
        "#months-multiselect .multiselect-select-all-checkbox"
    ).evaluate("e=>e===document.activeElement")
    before = page.locator('input[name="months"]:checked').count()
    page.locator('input[name="months"]').first.uncheck()
    assert page.locator('input[name="months"]:checked').count() == before - 1
    page.keyboard.press("Escape")
    assert display.get_attribute("aria-expanded") == "false"
    assert display.evaluate("e=>e===document.activeElement")


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_clients_layout_search_sort_and_report_selection(page, width):
    page.set_viewport_size({"width": width, "height": 844})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= innerWidth"
    ), page.evaluate(
        "()=>[...document.querySelectorAll('.app-main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&!e.closest('.sheet-scroller')).map(e=>({tag:e.tagName,class:e.className,text:e.textContent.slice(0,80)}))"
    )
    if width <= 768:
        assert page.locator("#clients-table").evaluate(
            "e=>getComputedStyle(e).minWidth === '0px'"
        )
        assert page.locator("#clients-table-wrapper .sheet-scroller").evaluate(
            "e=>e.scrollHeight <= e.clientHeight"
        )
    original = page.locator(".client-row").evaluate_all(
        "rows=>rows.map(r=>r.dataset.client)"
    )
    assert page.locator("#client-metric, #client-sort").count() == 0
    # Заголовок выбирает показатель и циклически переключает сортировку.
    weight = page.locator('th[data-sort="weight"]')
    weight.click()
    assert page.locator("#dynamics-metric-label").inner_text() == "(Вес)"
    assert page.locator("#delta-metric-label").inner_text() == "(Вес)"
    assert page.locator(".delta-value").first.inner_text() == "-60%"
    assert weight.get_attribute("aria-sort") == "descending"
    weight.focus()
    page.keyboard.press("Enter")
    assert weight.get_attribute("aria-sort") == "ascending"
    page.keyboard.press("Enter")
    assert weight.get_attribute("aria-sort") == "none"
    qty = page.locator('th[data-sort="qty"]')
    qty.click()
    assert page.locator("#dynamics-metric-label").inner_text() == "(Кол-во)"
    assert page.locator(".delta-value").first.inner_text() == "+100%"
    assert (
        page.locator(".client-row").first.get_attribute("data-client") == "Магазин Маяк"
    )
    qty.click()
    qty.click()
    assert (
        page.locator(".client-row").evaluate_all("rows=>rows.map(r=>r.dataset.client)")
        == original
    )
    page.locator("#client-type").select_option("Магазин", force=True)
    page.locator("#client-table-search").fill("Ничего подобного нет")
    page.locator("#client-table-search-reset").click()
    assert page.locator(".client-row:visible").count() == 1
    assert page.locator(".client-row:visible").get_attribute("data-type") == "Магазин"
    assert not page.locator("#clients-search-empty").is_visible()
    page.locator("#client-type").select_option("", force=True)
    page.locator("#client-table-search").fill("Ничего подобного нет")
    assert page.locator("#clients-search-empty").is_visible()
    page.locator("#client-table-search").fill("Северный берег")
    assert page.locator(".client-row:visible").count() == 1
    page.locator(".client-row:visible .ca-row-select").check()
    assert page.locator("#ca-selection-count").inner_text() == "1"
    page.locator("#client-table-search").fill("")
    assert page.locator("#ca-selection-count").inner_text() == "1"
    page.locator("#ca-selection-summary").click()
    page.wait_for_url("**/analytics/client-analysis?**")
    query = parse_qs(urlsplit(page.url).query)
    assert query["clients"] == ["Клуб с длинным названием — Северный берег"]
    assert query["city"] == ["Иркутск"]
    assert query["months"] == ["2026-07-01", "2026-08-01", "2026-09-01"]


def test_city_suggestions_mouse_and_keyboard(page):
    page.locator(".clients-filter-panel > summary").click()
    search = page.locator("#city-search")
    search.fill("Моск")
    page.keyboard.press("ArrowDown")
    assert search.get_attribute("aria-activedescendant")
    page.keyboard.press("Enter")
    page.wait_for_url(
        lambda url: parse_qs(urlsplit(url).query).get("city") == ["Москва"],
        wait_until="networkidle",
    )
    assert parse_qs(urlsplit(page.url).query)["city"] == ["Москва"]
    page.locator(".clients-filter-panel > summary").click()
    page.locator("#city-search").fill("Пят")
    page.locator("#city-dropdown .search-dropdown-item:visible").click()
    page.wait_for_url(
        lambda url: parse_qs(urlsplit(url).query).get("city") == ["Пятигорск"],
        wait_until="networkidle",
    )
    assert parse_qs(urlsplit(page.url).query)["city"] == ["Пятигорск"]


@pytest.mark.parametrize(
    "path",
    [
        "/?year=2026",
        "/analytics/charts?city=Иркутск&months=2026-07-01&months=2026-08-01&months=2026-09-01",
        "/analytics/client-analysis?tab=summary&city=Иркутск&months=2026-07-01&months=2026-08-01&months=2026-09-01",
        "/analytics/client-analysis?tab=sku_presence&city=Иркутск&months=2026-09-01&skus=UI-1",
    ],
)
def test_narrow_analytics_do_not_overflow_page(page, path):
    page.set_viewport_size({"width": 320, "height": 844})
    response = page.goto("https://pulse-ui.test" + path, wait_until="networkidle")
    assert response.status == 200
    assert page.evaluate(
        "document.documentElement.scrollWidth <= innerWidth"
    ), page.evaluate(
        "()=>[...document.querySelectorAll('.app-main *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1&&!e.closest('.sheet-scroller')).map(e=>({tag:e.tagName,class:e.className,text:e.textContent.slice(0,80)}))"
    )
