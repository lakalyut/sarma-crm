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


def test_miniapp_required_highlights_and_last_visit_labels(page):
    page.add_init_script(
        "window.Telegram={WebApp:{initData:'test',ready(){},expand(){}}};"
    )
    page.route("https://telegram.org/**", lambda route: route.fulfill(body=""))
    page.route(
        "**/ambassador/app/verify",
        lambda route: route.fulfill(
            json={
                "role": "ambassador",
                "city": "Иркутск",
                "can_record_visits": True,
            }
        ),
    )
    page.route(
        "**/ambassador/app/options",
        lambda route: route.fulfill(
            json={
                "cities": ["Иркутск"],
                "clients_by_city": {"Иркутск": ["Клиент <А>", "Новый клиент"]},
                "last_visits_by_city": {"Иркутск": {"Клиент <А>": "02.10.2026"}},
                "types_by_city": {"Иркутск": ["Кальянная"]},
                "guessed_segment_by_type": {},
                "abc_by_segment": {},
                "visit_goals": [],
                "products": [
                    {"id": 1, "category": "Табак", "brand": "Сарма", "flavor": "Мята"}
                ],
            }
        ),
    )
    page.route(
        "**/ambassador/app/visit-history?**", lambda r: r.fulfill(json={"history": []})
    )
    submitted = []
    saves = []

    def save(route):
        submitted.append(route.request.post_data_json)
        saves.append(route)

    def complete_save():
        saves.pop().fulfill(
            json={"ok": True, "demo": False, "last_visit_date": "08.10.2026"}
        )

    page.route("**/ambassador/app/visits", save)
    page.goto("https://pulse-ui.test/ambassador/app", wait_until="networkidle")
    page.locator("#submit-btn").click()
    for selector in [
        "#client-input",
        "#sku-classic",
        "#sku-strong",
        "#sku-light",
        "#people-count",
        "#goal-input",
        "#comment-input",
        "#aromas-toggle",
    ]:
        assert page.locator(selector).get_attribute("aria-invalid") == "true"
        target = (
            "#products-field .visit-collapse"
            if selector == "#aromas-toggle"
            else selector
        )
        assert page.locator(target).evaluate(
            "el => getComputedStyle(el).borderTopColor === getComputedStyle(document.querySelector('.invalid-note')).color"
        )
    assert not submitted
    page.locator("#client-input").fill("Клиент")
    assert (
        page.locator(".client-list-item").first.inner_text()
        == "Клиент <А>\nПоследний визит: 02.10.2026"
    )
    assert "Визитов пока нет" in page.locator(".client-list-item").nth(1).inner_text()
    page.locator(".client-last-visit").first.click()
    assert page.locator("#client-input").input_value() == "Клиент <А>"
    page.locator('#products-list input[type="checkbox"]').check()
    for field in ["sku-classic", "sku-strong", "sku-light", "people-count"]:
        page.locator("#" + field).fill("0")
    page.locator("#goal-input").fill("Обучение")
    page.locator("#comment-input").fill("Комментарий")
    page.locator("#sku-classic").fill("-1")
    page.locator("#submit-btn").click()
    assert not submitted
    assert page.locator("#sku-classic").get_attribute("aria-invalid") == "true"
    page.locator("#sku-classic").fill("0")
    assert page.locator('#visit-card [aria-invalid="true"]').count() == 0
    page.locator("#submit-btn").click()
    page.locator("#submit-btn .pulse-loader").wait_for(state="visible")
    assert page.locator("#submit-btn").is_disabled()
    assert page.locator("#submit-btn").inner_text() == "Записываем визит…"
    assert len(submitted) == 1
    complete_save()
    page.locator("#again-btn").wait_for(state="visible")
    assert submitted[0]["client"] == "Клиент <А>"
    page.locator("#again-btn").click()
    assert page.locator("#visit-card .is-invalid").count() == 0
    page.locator("#client-input").fill("Клиент <А>")
    assert (
        "Последний визит: 08.10.2026" in page.locator(".client-list-item").inner_text()
    )
    page.locator("#submit-btn").click()
    assert page.locator("#comment-input").get_attribute("aria-invalid") == "true"


@pytest.mark.parametrize("width", [320, 390, 768, 1440])
def test_admin_navigation_groups_and_responsive_workspace(page, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("https://pulse-ui.test/admin", wait_until="networkidle")
    assert page.locator(".admin-overview-grid > section").count() == 3
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    if width <= 768:
        page.locator("#sidebar-burger").click()
    group = page.locator('[data-admin-group="management"]')
    group.locator("summary").click()
    page.wait_for_function("localStorage.getItem('pulseAdminGroup:management') === '0'")
    page.goto("https://pulse-ui.test/admin/unmatched", wait_until="networkidle")
    assert not group.evaluate("el => el.open")
    assert page.locator('[data-admin-group="quality"]').evaluate("el => el.open")
    assert (
        page.locator('.admin-section-nav [aria-current="page"]').inner_text()
        == "Несопоставленные"
    )
    page.goto("https://pulse-ui.test/admin/users", wait_until="networkidle")
    assert group.evaluate("el => el.open")
    assert (
        page.locator('.admin-section-nav [aria-current="page"]').inner_text()
        == "Пользователи"
    )
    page.goto("https://pulse-ui.test/admin/imports", wait_until="networkidle")
    assert (
        page.locator('.admin-section-nav [aria-current="page"]').inner_text()
        == "История и удаление"
    )
    assert page.evaluate("document.documentElement.scrollWidth") <= width


def test_import_history_selection_to_filtered_preview(page, db_session):
    from app.models import EventLog

    db_session.add(EventLog(city="Иркутск", months="2026-08-01", rows_imported=2))
    db_session.commit()
    page.goto("https://pulse-ui.test/admin/imports", wait_until="networkidle")
    page.locator(".admin-history a", has_text="Выбрать период").click()
    assert page.locator("#delete-import-city").input_value() == "Иркутск"
    assert (
        page.locator("#delete-months-multiselect input:checked").input_value()
        == "2026-08-01"
    )
    page.get_by_role("button", name="Показать количество").click()
    page.locator('form[action="/admin/imports/delete/confirm"]').wait_for(
        state="visible"
    )
    assert "Найдено строк для удаления: 2" in page.locator("body").inner_text()
    assert (
        page.locator(
            'form[action="/admin/imports/delete/confirm"] input[name="city"]'
        ).input_value()
        == "Иркутск"
    )


@pytest.mark.parametrize(
    "font_family", ["Arial, sans-serif", "sans-serif", "monospace"]
)
def test_admin_heading_fits_narrow_screen_with_fallback_fonts(page, font_family):
    page.set_viewport_size({"width": 320, "height": 900})
    page.goto("https://pulse-ui.test/admin", wait_until="networkidle")
    # Запас для различий системных шрифтов в CI и увеличенного текста на телефоне.
    page.locator(".admin-page-heading h1").evaluate(
        "(el, font) => { el.style.fontFamily = font; el.style.fontSize = '32px'; }",
        font_family,
    )
    assert page.evaluate("document.documentElement.scrollWidth") <= 320
    assert page.locator(".admin-page-heading h1").evaluate(
        "el => el.getBoundingClientRect().right <= document.documentElement.clientWidth"
    )


def test_loading_delay_cleanup_and_reduced_motion(page):
    page.evaluate(
        "window.finishFast = PulseLoading.begin(document.querySelector('.app-shell'), {label:'Быстро'}); finishFast();"
    )
    assert page.locator(".pulse-loader").count() == 0
    page.emulate_media(reduced_motion="reduce")
    page.evaluate(
        "window.stopOld = PulseLoading.begin(document.querySelector('.app-shell'), {label:'Первый', mode:'pulse'}); void 0;"
    )
    page.locator(".pulse-loader").wait_for(state="visible")
    assert (
        page.locator(".pulse-loader img")
        .get_attribute("src")
        .startswith("/static/favicon.svg")
    )
    assert (
        page.locator(".pulse-loader-mark").evaluate(
            "el => getComputedStyle(el).animationName"
        )
        == "none"
    )
    page.evaluate(
        "window.stopNew = PulseLoading.begin(document.querySelector('.app-shell'), {label:'Второй'}); stopOld();"
    )
    page.locator(".pulse-loader").wait_for(state="visible")
    assert page.locator(".pulse-loader").inner_text() == "Второй"
    page.evaluate("stopNew()")
    assert page.locator(".pulse-loader").count() == 0
    assert page.locator(".app-shell").get_attribute("aria-busy") is None
    page.evaluate(
        "document.querySelector('form[method=get]').dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}));"
    )
    assert page.locator(".app-shell").get_attribute("aria-busy") == "true"
    assert not page.evaluate(
        "document.querySelector('form[method=get]').dispatchEvent(new Event('submit', {bubbles:true, cancelable:true}))"
    )
    page.evaluate(
        "window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}));"
    )
    assert page.locator(".app-shell").get_attribute("aria-busy") is None


def test_download_loading_error_retry_and_success(page):
    page.evaluate(
        """() => {
        const link = document.createElement('a');
        link.href='/analytics/client-analysis?download=1';
        link.id='test-download'; link.textContent='Скачать отчёт';
        document.querySelector('.app-shell').prepend(link);
    }"""
    )
    pending = []
    page.route(
        "**/analytics/client-analysis?download=1", lambda route: pending.append(route)
    )
    page.locator("#test-download").click()
    page.locator("#test-download .pulse-loader").wait_for(state="visible")
    assert len(pending) == 1
    assert page.locator("#test-download").get_attribute("aria-disabled") == "true"
    pending.pop().fulfill(status=500, body="error")
    page.locator("#pulse-download-error").wait_for(state="visible")
    assert page.locator("#test-download").inner_text() == "Скачать отчёт"
    page.get_by_role("button", name="Повторить", exact=True).click()
    page.locator("#test-download .pulse-loader").wait_for(state="visible")
    with page.expect_download() as download:
        pending.pop().fulfill(
            status=200,
            content_type="text/html",
            headers={"Content-Disposition": 'attachment; filename="pulse-test.html"'},
            body="<html>Report</html>",
        )
    assert download.value.suggested_filename == "pulse-test.html"
    assert page.locator("#pulse-download-error").count() == 0
    assert page.locator("#test-download").get_attribute("aria-busy") is None


def test_miniapp_boot_loading_and_retry(page):
    page.add_init_script(
        "window.Telegram={WebApp:{initData:'test',ready(){},expand(){}}};"
    )
    page.route("https://telegram.org/**", lambda route: route.fulfill(body=""))
    pending = []
    page.route("**/ambassador/app/verify", lambda route: pending.append(route))
    page.goto("https://pulse-ui.test/ambassador/app", wait_until="domcontentloaded")
    page.locator("#content .pulse-loader-pulse").wait_for(state="visible")
    assert page.locator("#content").get_attribute("aria-busy") == "true"
    assert page.locator("#tabs").is_hidden()
    pending.pop().fulfill(status=503, json={"detail": "Не удалось войти"})
    page.locator("#boot-retry").wait_for(state="visible")
    assert page.locator("#content .pulse-loader").count() == 0
    page.locator("#boot-retry").click()
    page.locator("#content .pulse-loader").wait_for(state="visible")
    page.route(
        "**/ambassador/app/options",
        lambda route: route.fulfill(
            json={
                "cities": ["Иркутск"],
                "clients_by_city": {"Иркутск": []},
                "types_by_city": {"Иркутск": ["HoReCa"]},
                "guessed_segment_by_type": {},
                "abc_by_segment": {},
                "products": [],
                "visit_goals": [],
            }
        ),
    )
    pending.pop().fulfill(
        json={
            "role": "ambassador",
            "city": "Иркутск",
            "first_name": "Тест",
            "can_record_visits": True,
        }
    )
    page.locator("#visit-card").wait_for(state="visible")
    page.wait_for_function(
        "document.getElementById('content').getAttribute('aria-busy') !== 'true'"
    )
    assert page.locator("#content .pulse-loader").count() == 0
    assert "Тест" in page.locator("#content").inner_text()

    # Initial client load and period refresh share the same feedback and retain old rows.
    pending_clients = []
    page.route(
        "**/ambassador/app/clients?**", lambda route: pending_clients.append(route)
    )
    page.locator("#tab-btn-clients").click()
    page.locator("#clients-list-content .pulse-loader").wait_for(state="visible")
    assert page.locator(".pulse-skeleton").count() == 3
    counts = {"ordered": 0, "total": 0}
    clients_body = {
        "rows": [
            {
                "client": "Кафе Тест",
                "sale_type": "HoReCa",
                "segment": "HoReCa",
                "has_orders": True,
                "abc": {"A": counts, "B": counts, "C": counts, "unrated": counts},
            }
        ],
        "month_from": "2026-09-01",
        "month_to": "2026-09-01",
        "months": [{"value": "2026-09-01", "label": "Сентябрь 2026"}],
    }
    pending_clients.pop().fulfill(json=clients_body)
    page.locator(".client-summary-row").wait_for(state="visible")
    page.locator("#clients-period-apply").click()
    page.locator("#clients-list-content .pulse-loader").wait_for(state="visible")
    assert "Кафе Тест" in page.locator(".client-summary-row").inner_text()
    assert page.locator("#clients-period-apply").is_disabled()
    pending_clients.pop().fulfill(status=503, json={"detail": "Временно недоступно"})
    page.locator("#clients-retry").wait_for(state="visible")
    assert page.locator("#clients-list-content .pulse-loader").count() == 0
    assert page.locator("#clients-period-apply").is_enabled()
    page.locator("#clients-retry").click()
    page.locator("#clients-list-content .pulse-loader").wait_for(state="visible")
    pending_clients.pop().fulfill(json=clients_body)
    page.locator(".client-summary-row").wait_for(state="visible")


def test_web_detail_loading_error_retry_and_cache(page):
    page.goto(
        "https://pulse-ui.test/analytics/client-analysis?city=Иркутск&months=2026-09-01&tab=summary",
        wait_until="networkidle",
    )
    pending = []
    page.route("**/api/client-analysis/clients?**", lambda route: pending.append(route))
    toggle = page.locator(
        '[data-ca-toggle][data-level="type"][aria-expanded="false"]'
    ).first
    toggle.click()
    page.locator(".ca-loading-feedback .pulse-loader").wait_for(state="visible")
    assert len(pending) == 1
    pending.pop().fulfill(status=503, json={"detail": "Ошибка"})
    page.locator('.ca-loading-feedback [role="alert"]').wait_for(state="visible")
    page.locator(".ca-loading-feedback button", has_text="Повторить").click()
    page.locator(".ca-loading-feedback .pulse-loader").wait_for(state="visible")
    assert len(pending) == 1
    pending.pop().fulfill(json=[])
    page.wait_for_function(
        "!document.querySelector('.ca-loading-feedback .pulse-loader')"
    )
    assert page.locator(".ca-loading-feedback .message").count() == 0
    page.locator(
        '[data-ca-toggle][data-level="type"][aria-expanded="true"]'
    ).last.click()
    page.locator(
        '[data-ca-toggle][data-level="type"][aria-expanded="false"]'
    ).last.click()
    assert not pending


def test_native_save_preserves_submitter_validation_and_blocks_duplicates(page):
    page.evaluate(
        """() => {
        const frame=document.createElement('iframe'); frame.name='native-save-target'; frame.hidden=true; document.body.append(frame);
        const form=document.createElement('form'); form.id='native-save'; form.method='post'; form.action='/admin/test-save'; form.target=frame.name;
        form.innerHTML='<input name="title" required><button id="save-button" name="operation" value="save" type="submit">Сохранить</button>';
        document.querySelector('.app-shell').prepend(form);
    }"""
    )
    pending = []
    page.route("**/admin/test-save", lambda route: pending.append(route))
    submit = "document.getElementById('native-save').requestSubmit(document.getElementById('save-button'));"
    page.evaluate(submit)
    assert not pending
    assert page.locator("#save-button").get_attribute("aria-busy") is None
    page.locator("#native-save input").fill("Название")
    page.evaluate(
        "document.getElementById('native-save').addEventListener('submit', e => e.preventDefault(), {once:true});"
    )
    page.evaluate(submit)
    assert not pending
    assert page.locator("#save-button").get_attribute("aria-busy") is None
    page.evaluate(submit)
    page.locator("#save-button .pulse-loader").wait_for(state="visible")
    assert page.locator("#save-button").inner_text() == "Сохраняем…"
    assert parse_qs(pending[0].request.post_data)["operation"] == ["save"]
    page.evaluate(submit)
    assert len(pending) == 1
    page.evaluate(
        "window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted:true}));"
    )
    assert page.locator("#save-button").inner_text() == "Сохранить"
    assert page.locator("#save-button").get_attribute("aria-busy") is None
    pending.pop().fulfill(
        content_type="text/html", body="<html><body>Сохранено</body></html>"
    )
    page.frame(name="native-save-target").wait_for_url("**/admin/test-save")


def test_web_navigation_skips_modified_clicks_and_shows_loading(page):
    started = []
    page.on(
        "console",
        lambda msg: (
            started.append(msg.text) if msg.text.startswith("navigation:") else None
        ),
    )
    page.evaluate(
        """() => {
        const a=document.createElement('a'); a.id='navigate-test'; a.href='/admin/users'; a.textContent='Пользователи';
        document.querySelector('.app-shell').prepend(a);
        a.addEventListener('click', e => { if (e.ctrlKey) e.preventDefault(); });
        // The DOM can't be queried while Playwright waits for a native navigation.
        const shell=document.querySelector('.app-shell');
        const observer=new MutationObserver(() => { if(shell.getAttribute('aria-busy') === 'true') console.log('navigation:busy'); });
        observer.observe(shell, {attributes:true, attributeFilter:['aria-busy']});
        a.dispatchEvent(new MouseEvent('click', {bubbles:true,ctrlKey:true,cancelable:true}));
    }"""
    )
    assert not started
    pending = []
    page.route("**/admin/users", lambda route: pending.append(route))
    page.evaluate("document.getElementById('navigate-test').click();")
    # Native navigation starts after the old page has entered its busy state.
    page.wait_for_timeout(100)
    assert started
    assert len(pending) == 1
    pending.pop().fulfill(
        content_type="text/html", body="<html><body>Пользователи</body></html>"
    )
    page.wait_for_url("**/admin/users")
