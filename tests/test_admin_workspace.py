import html
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from test_admin_imports_delete import CSRF_TOKEN, make_sale, seed_mixed_sales

from app.models import EventLog, Sale
from app.services.admin_workspace_service import admin_navigation, quality_counts


def test_admin_home_and_navigation(admin_client, db_session):
    seed_mixed_sales(db_session)
    response = admin_client.get("/admin")
    assert response.status_code == 200
    assert re.findall(r"<summary>(.*?)<span", response.text) == [
        "Управление",
        "Импорт данных",
        "Качество данных",
    ]
    assert response.text.count('class="admin-overview-card"') == 3
    assert 'aria-label="4 требуют проверки">4' in response.text
    assert "Справочники, импорт продаж" in response.text
    assert (
        admin_navigation("/admin/imports/delete")["admin_link"]["url"]
        == "/admin/imports"
    )
    assert admin_navigation("/admin/users/1/edit")["admin_group"]["id"] == "management"


@pytest.mark.parametrize("path", ["/admin", "/admin/imports", "/admin/imports/delete"])
def test_admin_workspace_requires_login(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


@pytest.mark.parametrize("role", ["user", "ambassador", "brand_ambassador"])
def test_admin_workspace_requires_admin(admin_client, admin_user, db_session, role):
    admin_user.role = role
    db_session.commit()
    for path in ["/admin", "/admin/imports"]:
        assert admin_client.get(path).status_code == 403


def test_import_history_prefills_scope_and_is_paginated(admin_client, db_session):
    seed_mixed_sales(db_session)
    for i in range(22):
        db_session.add(
            EventLog(
                city="Москва",
                months="2026-01-01, 2026-02-01",
                rows_imported=i + 1,
                rows_unmatched=1,
            )
        )
    db_session.add(EventLog(city="Казань", months="2026-03-01", rows_imported=1))
    db_session.commit()
    response = admin_client.get("/admin/imports?city=Москва")
    history = response.text.split('<section class="admin-history"')[1].split(
        "</section>"
    )[0]
    assert history.count("Выбрать период</a>") == 20
    link = html.unescape(
        re.search(r'href="([^"]+)" class="btn btn-secondary">Выбрать период', history)[
            1
        ]
    )
    assert parse_qs(urlsplit(link).query) == {
        "city": ["Москва"],
        "months": ["2026-01-01", "2026-02-01"],
    }
    selection = admin_client.get(link).text
    assert 'id="delete-import-city" value="Москва"' in selection
    assert (
        len(re.findall(r'name="months"\s+value="2026-0[12]-01"\s+checked', selection))
        == 2
    )
    assert (
        admin_client.get("/admin/imports?city=Москва&history_page=2").text.count(
            "Выбрать период</a>"
        )
        == 2
    )
    assert db_session.query(Sale).count() == 4


def test_multi_type_preview_and_confirm_keep_same_scope(admin_client, db_session):
    seed_mixed_sales(db_session)
    extra = make_sale(db_session, "Москва", "2026-01-01", "Магазин")
    data = {
        "city": "Москва",
        "months": ["2026-01-01"],
        "sale_types": ["HoReCa", "Розница"],
        "csrf_token": CSRF_TOKEN,
    }
    response = admin_client.post("/admin/imports/delete/preview", data=data)
    assert "Найдено строк для удаления: 2" in response.text
    confirm = response.text.split('action="/admin/imports/delete/confirm"')[1].split(
        "</form>"
    )[0]
    assert re.findall(r'name="sale_types" value="([^"]+)"', confirm) == [
        "HoReCa",
        "Розница",
    ]
    assert db_session.query(Sale).count() == 5
    response = admin_client.post("/admin/imports/delete/confirm", data=data)
    assert "Удалено строк: 2" in response.text
    db_session.expire_all()
    assert db_session.get(Sale, extra) is not None
    assert db_session.query(Sale).count() == 3


def test_quality_counts_include_missing_type(db_session):
    make_sale(db_session, "Москва", "2026-01-01", None)
    make_sale(db_session, "Москва", "2026-02-01", "HoReCa")
    assert quality_counts(db_session) == {"unmatched": 2, "nomenclature": 0, "types": 1}
