from urllib.parse import quote

import pandas as pd

from app.models import ClientNameAlias, Sale, Visit
from app.services.cities_service import rename_city
from app.services.client_name_review_service import (
    dismiss_names,
    get_review_groups,
    merge_names,
)
from app.services.import_service import IMPORT_COLUMNS, import_sales
from tests.conftest import CSRF_TOKEN

URL = "/admin/clients/review"
CITY = "Иркутск"
NAME = "Кафе Маяк"
SPACED = " Кафе\u00a0\tМаяк "


def sale(name, city=CITY):
    return Sale(city=city, client=name, month="Май 2026", type="HoReCa", weight=10)


def test_groups_case_whitespace_quotes_and_typos_but_not_branch_numbers(db_session):
    names = [
        NAME,
        SPACED,
        "КАФЕ МАЯК",
        "Кафе «Маяк»",
        "Кафе Мояк",
        "КафеМаяк",
        "Кафе Маяк 1",
        "Кафе Маяк 2",
    ]
    db_session.add_all([*(sale(name) for name in names), sale("Кафе Маак", "Москва")])
    db_session.commit()

    groups = get_review_groups(db_session, CITY)
    variants = [{row["name"] for row in group["rows"]} for group in groups]
    assert variants[0] == set(names[:4])
    assert {NAME, "Кафе Мояк"} in variants
    assert {NAME, "КафеМаяк"} in variants
    assert all("Кафе Маяк 1" not in group for group in variants)
    assert all("Кафе Маяк 2" not in group for group in variants)
    assert all("Кафе Маак" not in group for group in variants)


def test_address_variants_keep_branch_number(db_session):
    city = "Владивосток"
    name = "Papa`s Chilla"
    first = f"{name} (Владивосток, ул. Светланская 83)"
    second = f"{name} 2 (Владивосток, ул. Светланская, д. 83)"
    db_session.add_all(
        sale(variant, city)
        for variant in (name, f"{name} 2", first, second, f"{name} (ТЦ)")
    )
    db_session.commit()

    groups = get_review_groups(db_session, city)
    assert [{row["name"] for row in group["rows"]} for group in groups] == [
        {name, first},
        {f"{name} 2", second},
    ]


def test_preview_conflict_merge_and_reimport(admin_client, admin_user, db_session):
    db_session.add_all(
        [
            sale(NAME),
            sale(SPACED),
            sale(SPACED, "Москва"),
            Visit(
                city=CITY,
                client=SPACED,
                sale_type="HoReCa",
                ambassador_id=admin_user.id,
            ),
        ]
    )
    db_session.commit()
    page = admin_client.get(URL, params={"city": CITY})
    assert page.status_code == 200
    assert "Различаются пробелами" in page.text
    assert "Май 2026" in page.text
    assert "Проверить объединение" in page.text

    data = {
        "csrf_token": CSRF_TOKEN,
        "city": CITY,
        "variants": [quote(NAME), quote(SPACED)],
        "canonical": NAME,
    }
    response = admin_client.post(URL, data={**data, "operation": "preview"})
    assert response.status_code == 200
    assert 'name="expected_sales" value="1"' in response.text
    assert 'name="expected_visits" value="1"' in response.text
    assert db_session.query(ClientNameAlias).count() == 0

    db_session.add(sale(SPACED))
    db_session.commit()
    data |= {"operation": "merge", "expected_sales": 1, "expected_visits": 1}
    response = admin_client.post(URL, data=data)
    assert response.status_code == 400
    assert "Число строк изменилось" in response.text

    response = admin_client.post(URL, data={**data, "expected_sales": 2})
    assert response.status_code == 200
    assert "Объединение сохранено" in response.text
    assert db_session.query(Sale).filter_by(city=CITY, client=NAME).count() == 3
    assert db_session.query(Sale).filter_by(city="Москва").one().client == SPACED
    assert db_session.query(Visit).one().client == NAME

    rename_city(db_session, CITY, "Новый Иркутск")
    frame = pd.DataFrame(
        [["Июнь 2026", "HoReCa", SPACED, "Тест", "SKU", 1, 10]],
        columns=IMPORT_COLUMNS,
    )
    import_sales(db_session, frame, "Новый Иркутск", admin_user.id)
    assert (
        db_session.query(Sale).filter_by(city="Новый Иркутск", client=NAME).count() == 4
    )


def test_dismissal_persists_when_another_variant_is_merged(db_session):
    typo = "Кафе Мояк"
    db_session.add_all([sale(NAME), sale(typo), sale(SPACED)])
    db_session.commit()
    dismiss_names(db_session, CITY, [NAME, typo])
    assert {NAME, typo} not in [
        {row["name"] for row in group["rows"]}
        for group in get_review_groups(db_session, CITY)
    ]
    merge_names(db_session, CITY, [NAME, SPACED], "Кафе «Маяк»", expected_counts=(2, 0))
    assert get_review_groups(db_session, CITY) == []
    assert (
        db_session.get(ClientNameAlias, (CITY, SPACED)).canonical_name == "Кафе «Маяк»"
    )
