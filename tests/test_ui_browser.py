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
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True
    )

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


@pytest.mark.parametrize("touch", [False, True], ids=["mouse", "touch"])
def test_city_suggestions_mouse_and_keyboard(page, touch):
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
    option = page.locator("#city-dropdown .search-dropdown-item:visible")
    if touch:
        option.tap()
    else:
        option.click()
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


@pytest.mark.parametrize("touch", [False, True], ids=["mouse", "touch"])
def test_custom_select_pointer_commits_on_first_attempt(page, touch):
    page.locator(".clients-filter-panel > summary").click()
    select = page.locator("#field-matched")
    display = page.locator("#field-matched + .custom-select-display")
    page.evaluate(
        "window.selectChanges=0;document.querySelector('#field-matched').addEventListener('change',()=>window.selectChanges++)"
    )
    for count, value in enumerate(["1", "0", ""], start=1):
        if touch:
            display.tap()
        else:
            display.click()
        option = page.locator(
            f'#field-matched ~ .custom-select-dropdown [data-value="{value}"]'
        )
        if touch:
            option.tap()
        else:
            option.click()
        assert select.input_value() == value
        assert page.evaluate("window.selectChanges") == count
        assert display.get_attribute("aria-expanded") == "false"
    display.click()
    page.locator("h1").click()
    assert display.get_attribute("aria-expanded") == "false"


@pytest.mark.parametrize("touch", [False, True], ids=["mouse", "touch"])
def test_multiselect_label_pointer_preserves_selection_and_popup(page, touch):
    page.locator(".clients-filter-panel > summary").click()
    display = page.locator("#months-multiselect .multiselect-display")
    if touch:
        display.tap()
    else:
        display.click()
    checkbox = page.locator('#months-multiselect input[name="months"]').first
    label = page.locator("#months-multiselect .mp-month-chip").first
    for checked in [False, True]:
        # Край метки не перекрыт прозрачным input: это реальный клик
        # по label, а не прямое переключение самого чекбокса.
        if touch:
            label.tap(position={"x": 4, "y": 4})
        else:
            label.click(position={"x": 4, "y": 4})
        assert checkbox.is_checked() == checked
        assert display.get_attribute("aria-expanded") == "true"
    page.locator("h1").click()
    assert display.get_attribute("aria-expanded") == "false"


def test_selected_filters_share_highlight_and_clear(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    city = page.locator(".filter-field:has(#city-hidden)")
    months = page.locator(".filter-field:has(#months-multiselect)")
    types = page.locator(".filter-field:has(#types-multiselect)")
    matched = page.locator(".filter-field:has(#field-matched)")
    assert city.evaluate("e=>e.classList.contains('filter-selected')")
    assert months.evaluate("e=>e.classList.contains('filter-selected')")
    assert not types.evaluate("e=>e.classList.contains('filter-selected')")
    color = page.locator("#city-search").evaluate(
        "e=>getComputedStyle(e).backgroundColor"
    )
    assert (
        page.locator("#months-multiselect .multiselect-display").evaluate(
            "e=>getComputedStyle(e).backgroundColor"
        )
        == color
    )

    page.locator("#types-multiselect .multiselect-display").click()
    page.locator('#types-multiselect input[name="sale_types"]').first.check()
    assert types.evaluate("e=>e.classList.contains('filter-selected')")
    assert (
        page.locator("#types-multiselect .multiselect-display").evaluate(
            "e=>getComputedStyle(e).backgroundColor"
        )
        == color
    )
    all_types = page.locator("#types-multiselect .multiselect-select-all-checkbox")
    all_types.check()
    all_types.uncheck()
    assert not types.evaluate("e=>e.classList.contains('filter-selected')")
    page.locator("h1").click()

    # «Нет» имеет значение 0: это выбранный фильтр, а не пустое значение.
    page.select_option("#field-matched", "0", force=True)
    assert matched.evaluate("e=>e.classList.contains('filter-selected')")
    page.select_option("#field-matched", "", force=True)
    assert not matched.evaluate("e=>e.classList.contains('filter-selected')")
    page.locator("#months-multiselect .multiselect-display").click()
    page.locator("#months-multiselect .multiselect-select-all-checkbox").uncheck()
    assert not months.evaluate("e=>e.classList.contains('filter-selected')")


def test_tag_filter_highlight_follows_selection_removal_and_reload(page):
    url = "https://pulse-ui.test/analytics/client-analysis?city=Иркутск&tab=summary"
    page.goto(url, wait_until="networkidle")
    field = page.locator(".filter-field:has(#ca-client-search)")
    assert not field.evaluate("e=>e.classList.contains('filter-selected')")
    page.locator("#ca-client-search").fill("Северный")
    page.locator("#ca-client-dropdown .search-dropdown-item:not(.hidden)").click()
    page.wait_for_function(
        "document.querySelector('#ca-client-search').closest('.field').classList.contains('filter-selected')"
    )
    assert page.locator('#ca-clients-tags input[name="clients"]').count() == 1
    page.locator("#ca-clients-tags .filter-tag-remove").click()
    page.wait_for_function(
        "!document.querySelector('#ca-client-search').closest('.field').classList.contains('filter-selected')"
    )
    assert page.locator('#ca-clients-tags input[name="clients"]').count() == 0
    page.goto(url + "&clients=Магазин%20Маяк", wait_until="networkidle")
    assert field.evaluate("e=>e.classList.contains('filter-selected')")


def test_region_filter_highlight_tracks_tags(page):
    page.goto("https://pulse-ui.test/analytics/regions", wait_until="networkidle")
    field = page.locator(".filter-field:has(#regions-city-search)")
    assert not field.evaluate("e=>e.classList.contains('filter-selected')")
    page.locator("#regions-city-search").fill("Москва")
    page.locator(
        "#regions-city-dropdown .search-dropdown-item:not(.hidden) input"
    ).check()
    page.wait_for_function(
        "document.querySelector('#regions-city-search').closest('.field').classList.contains('filter-selected')"
    )
    page.locator("h1").click()
    page.locator("#regions-cities-tags .filter-tag-remove").click()
    page.wait_for_function(
        "!document.querySelector('#regions-city-search').closest('.field').classList.contains('filter-selected')"
    )
    assert page.locator('#regions-cities-tags input[name="cities"]').count() == 0


def test_ajax_filter_options_clear_highlight_after_city_change(page):
    page.goto("https://pulse-ui.test/admin/imports/delete", wait_until="networkidle")
    months = page.locator(".filter-field:has(#delete-months-multiselect)")
    page.locator("#delete-import-city-search").fill("Иркутск")
    page.locator('#delete-import-city-dropdown [data-value="Иркутск"]').click()
    page.wait_for_function(
        "document.querySelectorAll('#delete-months-multiselect input[name=months]').length > 0"
    )
    page.locator("#delete-months-multiselect .multiselect-display").click()
    page.locator('#delete-months-multiselect input[name="months"]').first.check()
    assert months.evaluate("e=>e.classList.contains('filter-selected')")
    page.locator("h1").click()
    page.locator("#delete-import-city-search").fill("Москва")
    page.locator('#delete-import-city-dropdown [data-value="Москва"]').click()
    page.wait_for_function(
        "document.querySelectorAll('#delete-months-multiselect input[name=months]').length > 0"
    )
    page.wait_for_function(
        "!document.querySelector('#delete-months-multiselect').closest('.field').classList.contains('filter-selected')"
    )
    assert (
        page.locator('#delete-months-multiselect input[name="months"]:checked').count()
        == 0
    )
