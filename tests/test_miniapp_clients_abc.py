import pytest
from conftest import signed_init_data

from app.auth_models import User
from app.models import AbcSegment, Product, ProductAbcRating, Sale


@pytest.fixture
def abc_data(db_session):
    horeca = AbcSegment(name="HoReCa", sort_order=0)
    retail = AbcSegment(name="Розница", sort_order=1)
    db_session.add_all([horeca, retail])
    db_session.flush()
    products = {}
    for sku in ("A1", "A2", "B1", "C1", "U1", "OLD"):
        product = Product(
            category="Табак",
            brand="Бренд",
            flavor=sku,
            canonical_sku=sku,
            canonical_name=sku,
            norm_brand="бренд",
            norm_flavor=sku.lower(),
            is_active=sku != "OLD",
        )
        db_session.add(product)
        db_session.flush()
        products[sku] = product
        category = {"A1": "A", "A2": "A", "B1": "B", "C1": "C", "OLD": "A"}.get(sku)
        if category:
            db_session.add(
                ProductAbcRating(
                    product_id=product.id, segment_id=horeca.id, category=category
                )
            )
            db_session.add(
                ProductAbcRating(
                    product_id=product.id,
                    segment_id=retail.id,
                    category="C" if sku == "A1" else category,
                )
            )
    user = User(
        email="abc-amb@test.local",
        role="ambassador",
        is_active=True,
        telegram_id=5553330001,
        first_name="Иван",
        city="Иркутск",
    )
    db_session.add(user)
    db_session.commit()
    return user, products


def sale(
    db,
    products,
    sku,
    month="2026-05-01",
    qty=1,
    city="Иркутск",
    client="Кафе",
    point_type="HoReCa",
):
    product = products.get(sku)
    db.add(
        Sale(
            city=city,
            client=client,
            type=point_type,
            month=month,
            product_id=product.id if product else None,
            sku=sku,
            name=sku,
            qty=qty,
            weight=qty * 5,
            matched=bool(product),
        )
    )
    db.commit()


def headers(user):
    return {"Authorization": "tma " + signed_init_data(user.telegram_id)}


def test_latest_available_month_not_calendar_or_other_city(
    client, db_session, abc_data
):
    user, products = abc_data
    sale(db_session, products, "A1", "2025-12-01", qty=10)
    sale(db_session, products, "B1", "2026-05-01", qty=2)
    sale(db_session, products, "C1", "2026-09-01", city="Москва")
    response = client.get("/ambassador/app/clients?city=Москва", headers=headers(user))
    assert response.status_code == 200
    data = response.json()
    assert data["month_from"] == data["month_to"] == "2026-05-01"
    assert data["rows"][0]["abc"]["A"] == {"ordered": 0, "total": 2}
    assert data["rows"][0]["abc"]["B"] == {"ordered": 1, "total": 1}


def test_distinct_skus_and_missing_catalog_items_in_detail(
    client, db_session, abc_data
):
    user, products = abc_data
    sale(db_session, products, "A1", qty=10)
    sale(db_session, products, "A1", qty=20)
    sale(db_session, products, "U1", qty=3)
    sale(db_session, products, "RAW", qty=2)
    sale(db_session, products, "OLD", qty=1)
    response = client.get(
        "/ambassador/app/client-detail",
        params={"client": "Кафе", "sale_type": "HoReCa"},
        headers=headers(user),
    )
    data = response.json()
    assert data["abc"]["A"] == {"ordered": 1, "total": 2}
    groups = {g["category"]: g for g in data["groups"]}
    items = {i["sku"]: i for i in groups["A"]["items"]}
    assert items["A1"]["qty"] == 30
    assert items["A1"]["ordered"] is True
    assert items["A2"]["ordered"] is False
    assert items["A2"]["name"] == "Бренд — A2"
    assert {i["sku"] for i in groups["unrated"]["items"]} == {"U1", "RAW", "OLD"}
    assert data["segment"] == "HoReCa"


def test_range_and_both_month_formats_are_combined(client, db_session, abc_data):
    user, products = abc_data
    sale(db_session, products, "A1", "Май 2026", qty=2)
    sale(db_session, products, "A1", "2026-05-01", qty=3)
    sale(db_session, products, "B1", "2026-06-01", qty=4)
    query = {"month_from": "2026-05-01", "month_to": "2026-06-01"}
    data = client.get(
        "/ambassador/app/clients", params=query, headers=headers(user)
    ).json()
    assert len(data["months"]) == 2
    assert data["rows"][0]["abc"]["A"]["ordered"] == 1
    assert data["rows"][0]["abc"]["B"]["ordered"] == 1
    detail = client.get(
        "/ambassador/app/client-detail",
        params={**query, "client": "Кафе", "sale_type": "HoReCa"},
        headers=headers(user),
    ).json()
    assert detail["groups"][0]["items"][0]["qty"] == 5


def test_segment_per_point_type_and_client_with_no_orders(client, db_session, abc_data):
    user, products = abc_data
    sale(db_session, products, "A1", point_type="HoReCa")
    sale(db_session, products, "A1", point_type="Розница")
    sale(db_session, products, "A2", month="2026-04-01", client="Бывший клиент")
    data = client.get("/ambassador/app/clients", headers=headers(user)).json()
    rows = {(r["client"], r["sale_type"]): r for r in data["rows"]}
    assert rows[("Кафе", "HoReCa")]["abc"]["A"]["ordered"] == 1
    assert rows[("Кафе", "Розница")]["abc"]["C"]["ordered"] == 1
    assert rows[("Бывший клиент", "HoReCa")]["has_orders"] is False
    assert rows[("Бывший клиент", "HoReCa")]["abc"]["A"]["ordered"] == 0


@pytest.mark.parametrize(
    "query",
    [
        {"month_from": "2099-01-01"},
        {"month_from": "2026-06-01", "month_to": "2026-05-01"},
    ],
)
def test_invalid_period_has_clear_error(client, db_session, abc_data, query):
    user, products = abc_data
    sale(db_session, products, "A1")
    sale(db_session, products, "B1", "2026-06-01")
    response = client.get(
        "/ambassador/app/clients", params=query, headers=headers(user)
    )
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)


def test_empty_city_no_period_and_no_foreign_catalog(client, db_session, abc_data):
    user, products = abc_data
    sale(db_session, products, "A1", city="Москва")
    data = client.get("/ambassador/app/clients", headers=headers(user)).json()
    assert data["rows"] == [] and data["months"] == []
    data = client.get(
        "/ambassador/app/client-detail",
        params={"client": "Кафе", "sale_type": "HoReCa"},
        headers=headers(user),
    ).json()
    assert data["groups"] == []


def test_without_ratings_or_type_and_zero_quantity(client, db_session, abc_data):
    user, products = abc_data
    sale(db_session, products, "U1", qty=0, point_type=None)
    data = client.get("/ambassador/app/clients", headers=headers(user)).json()
    assert data["rows"][0]["has_orders"] is False
    data = client.get(
        "/ambassador/app/client-detail",
        params={"client": "Кафе", "sale_type": ""},
        headers=headers(user),
    ).json()
    assert data["abc"]["unrated"]["ordered"] == 0
    assert data["groups"][3]["items"][0]["ordered"] is False


def test_duplicate_catalog_sku_counted_once(client, db_session, abc_data):
    user, products = abc_data
    first = products["A1"]
    second = Product(
        category=first.category,
        brand=first.brand,
        flavor=first.flavor,
        canonical_sku="A1",
        canonical_name="A1 50г",
        norm_brand=first.norm_brand,
        norm_flavor=first.norm_flavor,
        is_active=True,
    )
    db_session.add(second)
    db_session.commit()
    sale(db_session, products, "A1", qty=2)
    db_session.add(
        Sale(
            city="Иркутск",
            client="Кафе",
            type="HoReCa",
            month="2026-05-01",
            product_id=second.id,
            sku="A1",
            qty=3,
            weight=1,
        )
    )
    db_session.commit()
    data = client.get("/ambassador/app/clients", headers=headers(user)).json()
    assert data["rows"][0]["abc"]["A"] == {"ordered": 1, "total": 2}
