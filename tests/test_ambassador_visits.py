import pytest
from conftest import signed_init_data


def _make_region_with_sales(db_session):
    from app.models import CityRegion, Region, Sale

    region = Region(name="Тестовый регион", sort_order=0)
    db_session.add(region)
    db_session.commit()
    db_session.refresh(region)

    db_session.add(CityRegion(city="Тестгород", region_id=region.id))
    db_session.add(
        Sale(
            city="Тестгород",
            month="2026-01-01",
            type="Кальянная",
            client="Клиент А",
            product_id=None,
            qty=1,
            weight=1,
        )
    )
    db_session.commit()
    return region


def _make_product(db_session, category="Табак", flavor="Мята"):
    from app.models import Product

    product = Product(
        category=category,
        brand="Тестбренд",
        flavor=flavor,
        canonical_sku="TEST-SKU",
        canonical_name=f"Тестбренд {flavor}",
        norm_brand="тестбренд",
        norm_flavor=flavor.lower(),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def _make_ambassador(db_session, region_id, telegram_id=999111):
    from app.auth_models import User

    user = User(
        email="visit-amb@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=telegram_id,
        first_name="Виз",
        last_name="Итов",
        region_id=region_id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_get_cities_for_region(db_session):
    from app.services.ambassador_service import get_cities_for_region

    region = _make_region_with_sales(db_session)
    assert get_cities_for_region(db_session, region.id) == ["Тестгород"]


def test_get_visit_options_scoped_to_region(db_session):
    from app.services.ambassador_service import get_visit_options

    region = _make_region_with_sales(db_session)
    product = _make_product(db_session)

    options = get_visit_options(db_session, region.id)

    assert options["cities"] == ["Тестгород"]
    assert options["clients_by_city"]["Тестгород"] == ["Клиент А"]
    assert options["types_by_city"]["Тестгород"] == ["Кальянная"]
    assert any(p["id"] == product.id for p in options["products"])
    matched = next(p for p in options["products"] if p["id"] == product.id)
    assert matched["sku"] == "TEST-SKU"


def test_create_visit_happy_path(db_session):
    from app.models import Visit, VisitProduct
    from app.services.ambassador_service import create_visit

    region = _make_region_with_sales(db_session)
    product = _make_product(db_session)
    ambassador = _make_ambassador(db_session, region.id)

    visit = create_visit(
        db_session,
        ambassador,
        city="Тестгород",
        client="Клиент А",
        sale_type="Кальянная",
        product_ids=[product.id],
    )

    assert db_session.query(Visit).filter(Visit.id == visit.id).count() == 1
    assert (
        db_session.query(VisitProduct)
        .filter(
            VisitProduct.visit_id == visit.id, VisitProduct.product_id == product.id
        )
        .count()
        == 1
    )


def test_create_visit_rejects_city_outside_region(db_session):
    from app.services.ambassador_service import create_visit

    region = _make_region_with_sales(db_session)
    product = _make_product(db_session)
    ambassador = _make_ambassador(db_session, region.id)

    with pytest.raises(ValueError):
        create_visit(
            db_session,
            ambassador,
            city="Чужой город",
            client="Клиент А",
            sale_type="Кальянная",
            product_ids=[product.id],
        )


def test_create_visit_rejects_unknown_client(db_session):
    from app.services.ambassador_service import create_visit

    region = _make_region_with_sales(db_session)
    product = _make_product(db_session)
    ambassador = _make_ambassador(db_session, region.id)

    with pytest.raises(ValueError):
        create_visit(
            db_session,
            ambassador,
            city="Тестгород",
            client="Незнакомый клиент",
            sale_type="Кальянная",
            product_ids=[product.id],
        )


def test_create_visit_rejects_empty_products(db_session):
    from app.services.ambassador_service import create_visit

    region = _make_region_with_sales(db_session)
    ambassador = _make_ambassador(db_session, region.id)

    with pytest.raises(ValueError):
        create_visit(
            db_session,
            ambassador,
            city="Тестгород",
            client="Клиент А",
            sale_type="Кальянная",
            product_ids=[],
        )


def test_post_visits_happy_path(db_session, client):
    from app.models import Visit

    region = _make_region_with_sales(db_session)
    product = _make_product(db_session)
    ambassador = _make_ambassador(db_session, region.id)

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.post(
        "/ambassador/app/visits",
        headers={"Authorization": f"tma {init_data}"},
        json={
            "city": "Тестгород",
            "client": "Клиент А",
            "sale_type": "Кальянная",
            "product_ids": [product.id],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert db_session.query(Visit).count() == 1


def test_post_visits_rejects_invalid_city(db_session, client):
    region = _make_region_with_sales(db_session)
    product = _make_product(db_session)
    ambassador = _make_ambassador(db_session, region.id)

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.post(
        "/ambassador/app/visits",
        headers={"Authorization": f"tma {init_data}"},
        json={
            "city": "Чужой город",
            "client": "Клиент А",
            "sale_type": "Кальянная",
            "product_ids": [product.id],
        },
    )

    assert resp.status_code == 400
