import re
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


def test_inline_address_formatting_in_kazan(admin_client, db_session):
    city = "Казань"
    askar = "Аскар Трилион(сервис), Татарстан 43а"
    askar_variant = "Аскар Трилион (сервис); Татарстан, 43А"
    feel = 'Заведение "Feel house"; Курынова, 6, к1'
    feel_variant = 'Заведение "Feel house"; ул. Курынова 6 корп 1'
    db_session.add_all(
        sale(name, city)
        for name in (
            askar,
            askar_variant,
            askar.replace("43а", "43б"),
            feel,
            feel_variant,
            feel.replace("к1", "к2"),
        )
    )
    db_session.commit()
    groups = get_review_groups(db_session, city)
    assert [{row["name"] for row in group["rows"]} for group in groups] == [
        {askar, askar_variant},
        {feel, feel_variant},
    ]
    bulk_url = URL + "/bulk"
    preview = admin_client.get(bulk_url, params={"city": city})
    assert "Групп к объединению — 2" in preview.text
    assert "43б" not in preview.text
    assert "к2" not in preview.text
    snapshot = re.search(r'name="snapshot" value="([a-f0-9]+)"', preview.text)[1]
    response = admin_client.post(
        bulk_url,
        data={"city": city, "snapshot": snapshot, "csrf_token": CSRF_TOKEN},
    )
    assert response.status_code == 200
    assert "Обновлено строк продаж — 2" in response.text
    assert db_session.query(Sale.client).filter_by(city=city).distinct().count() == 4


def test_payment_notes_with_same_address(db_session):
    city = "СПБ"
    first = "42 Lounge (пр. Просвещения, 33, корпус 1)- (Н)"
    second = "42 Lounge (пр. Просвещения, 33, корпус 1)- (НАЛ)"
    db_session.add_all(
        sale(name, city)
        for name in (first, second, first.replace("корпус 1", "корпус 2"))
    )
    db_session.commit()
    groups = get_review_groups(db_session, city)
    assert [{row["name"] for row in group["rows"]} for group in groups] == [
        {first, second}
    ]
    assert groups[0]["reason"] == "Различаются пометками (Н) / (НАЛ)"
    dismiss_names(db_session, city, [first, second])
    assert get_review_groups(db_session, city) == []


def test_high_similarity_and_city_filter(admin_client, db_session):
    first = "Кальянная Северный берег обслуживание клиентов"
    second = "Кальянная Севирный берег обслуживанеи клиентов"
    db_session.add_all(
        [
            sale(first, "Казань"),
            sale(second, "Казань"),
            sale(first + " 2", "Казань"),
            sale(second + " 3", "Казань"),
            sale("Отдельный клиент", "Омск"),
            Sale(city="Пермь", client="Точка без типа", type="nan"),
        ]
    )
    db_session.commit()
    page = admin_client.get(URL, params={"city": "Казань"})
    assert 'value="Казань" selected' in page.text
    assert 'value="Пермь"' in page.text
    assert 'value="Омск"' not in page.text
    groups = get_review_groups(db_session, "Казань")
    assert [{row["name"] for row in group["rows"]} for group in groups] == [
        {first, second}
    ]
    assert groups[0]["reason"].startswith("Сходство названий")
    dismiss_names(db_session, "Казань", [first, second])
    assert 'value="Казань"' not in admin_client.get(URL).text


def test_bulk_review_merges_only_previewed_exact_groups(admin_client, db_session):
    original = "Papa’s Chilla"
    alternative = " «PAPA’S  CHILLA» "
    branch = "Papa’s Chilla 2"
    rejected = ("Розница Плюс", "РОЗНИЦА ПЛЮС")
    db_session.add_all(
        sale(name)
        for name in (original, original, alternative, branch, NAME, SPACED, *rejected)
    )
    db_session.add(sale(alternative, "Москва"))
    db_session.commit()
    dismiss_names(db_session, CITY, rejected)

    bulk_url = URL + "/bulk"

    def get_snapshot():
        response = admin_client.get(bulk_url, params={"city": CITY})
        assert "Групп к объединению — 2" in response.text
        assert branch not in response.text
        assert rejected[0] not in response.text
        return re.search(r'name="snapshot" value="([a-f0-9]+)"', response.text)[1]

    data = {"csrf_token": CSRF_TOKEN, "city": CITY, "snapshot": get_snapshot()}
    db_session.add(sale(alternative))
    db_session.commit()
    assert admin_client.post(bulk_url, data=data).status_code == 400
    assert db_session.query(ClientNameAlias).count() == 0
    assert (
        admin_client.post(
            bulk_url, data={**data, "snapshot": get_snapshot()}
        ).status_code
        == 200
    )
    assert db_session.query(Sale).filter_by(city=CITY, client=original).count() == 4
    assert db_session.query(Sale).filter_by(city=CITY, client=NAME).count() == 2
    assert db_session.query(Sale).filter_by(city=CITY, client=branch).count() == 1
    assert (
        db_session.query(Sale).filter_by(city="Москва", client=alternative).count() == 1
    )
    assert (
        db_session.get(ClientNameAlias, (CITY, alternative)).canonical_name == original
    )


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


def test_assign_city_point_type_to_only_missing_sales(admin_client, db_session):
    other_city = "Москва"
    db_session.add_all(
        [
            Sale(city=CITY, client=NAME, type=point_type)
            for point_type in (" NaN ", None, "", "\u00a0nan\t", "\u200b", "HoReCa")
        ]
        + [
            Sale(city=CITY, client="Другая точка", type="nan"),
            Sale(city=CITY, client="Магазин", type="Розница"),
            Sale(city=other_city, client=NAME, type="nan"),
            Sale(city=other_city, client="Точка", type="Тип другого города"),
        ]
    )
    db_session.commit()

    page = admin_client.get(URL, params={"city": CITY})
    assert "Клиенты без типа точки · 2" in page.text
    assert '<option value="HoReCa" selected>' in page.text
    assert '<option value="Розница">' in page.text
    assert "Тип другого города" not in page.text
    data = {"csrf_token": CSRF_TOKEN, "city": CITY, "client": quote(NAME)}
    assert (
        admin_client.post(
            URL + "/point-type", data={**data, "point_type": "Тип другого города"}
        ).status_code
        == 400
    )

    response = admin_client.post(
        URL + "/point-type", data={**data, "point_type": "Розница"}
    )
    assert response.status_code == 200
    assert "Обновлено строк продаж — 5." in response.text
    assert "Клиенты без типа точки · 1" in response.text
    assert (
        db_session.query(Sale).filter_by(city=CITY, client=NAME, type="HoReCa").count()
        == 1
    )
    assert (
        db_session.query(Sale).filter_by(city=CITY, client=NAME, type="Розница").count()
        == 5
    )
    assert (
        db_session.query(Sale).filter_by(city=other_city, client=NAME).one().type
        == "nan"
    )
