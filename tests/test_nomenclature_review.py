"""Ревизия номенклатуры — дрейф sale.sku после правки товара + предупреждение
о дубле по вкусу."""

from conftest import CSRF_TOKEN


def _product(db_session, brand, flavor, sku=None):
    from app.models import Product
    from app.product_parser import normalize_text

    sku = sku or f'Табак "{brand}" {flavor}'
    p = Product(
        category="Табак",
        brand=brand,
        flavor=flavor,
        canonical_sku=sku,
        canonical_name=f"{sku} 25г.",
        default_weight_g=25,
        norm_brand=normalize_text(brand),
        norm_flavor=normalize_text(flavor),
        is_active=True,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _sale(db_session, product, sku=None, city="Иркутск"):
    from app.models import Sale

    s = Sale(
        city=city,
        month="2026-09-01",
        type="HoReCa",
        client="Кафе А",
        raw_name=f"Табак {product.brand} {product.flavor} 25г",
        raw_sku="RAW-1",
        product_id=product.id,
        sku=sku if sku is not None else product.canonical_sku,
        name=f"{product.canonical_sku} 25г.",
        qty=5,
        weight=125,
        matched=True,
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_no_drift_when_sale_matches_product(db_session):
    from app.services.nomenclature_review_service import get_drift_groups

    p = _product(db_session, "Сарма 360", "Ваниль")
    _sale(db_session, p)
    assert get_drift_groups(db_session) == []


def test_drift_detected_after_brand_fix(db_session):
    from app.product_parser import build_canonical_sku, normalize_text
    from app.services.nomenclature_review_service import (
        get_drift_groups,
        product_drift_count,
        resync_product_sales,
    )

    p = _product(db_session, "Сарма", "Ваниль")
    _sale(db_session, p)  # sale.sku = старый 'Табак "Сарма" Ваниль'

    # правим бренд, как edit_product
    p.brand = "Сарма 360"
    p.norm_brand = normalize_text("Сарма 360")
    p.canonical_sku = build_canonical_sku("Табак", "Сарма 360", None, "Ваниль")
    db_session.commit()

    assert product_drift_count(db_session, p.id) == 1
    groups = get_drift_groups(db_session)
    assert len(groups) == 1
    assert groups[0]["count"] == 1
    assert groups[0]["cities"] == ["Иркутск"]

    n = resync_product_sales(db_session, p.id)
    assert n == 1
    assert product_drift_count(db_session, p.id) == 0

    from app.models import Sale

    db_session.expire_all()
    assert db_session.query(Sale).first().sku == p.canonical_sku


def test_resync_all(db_session):
    from app.services.nomenclature_review_service import resync_all

    p1 = _product(db_session, "Сарма", "Ваниль")
    p2 = _product(db_session, "Сарма", "Мята")
    _sale(db_session, p1, sku="СТАРОЕ-1")
    _sale(db_session, p2, sku="СТАРОЕ-2")

    assert resync_all(db_session) == 2
    assert resync_all(db_session) == 0  # второй прогон — нечего чинить


def test_flavor_collision(db_session):
    from app.services.nomenclature_review_service import flavor_collision

    _product(db_session, "Сарма 360", "Ваниль")
    wrong = _product(db_session, "Сарма", "Ваниль")

    other = flavor_collision(db_session, wrong)
    assert other is not None
    assert other.brand == "Сарма 360"

    lone = _product(db_session, "Сарма 360", "Личи")
    assert flavor_collision(db_session, lone) is None


def test_review_page_and_resync_route(admin_client, db_session):
    from app.models import Sale

    p = _product(db_session, "Сарма 360", "Ваниль", sku="НОВЫЙ-SKU")
    _sale(db_session, p, sku="СТАРЫЙ-SKU")

    resp = admin_client.get("/admin/nomenclature/review")
    assert resp.status_code == 200
    assert "СТАРЫЙ-SKU" in resp.text

    resp = admin_client.post(
        f"/admin/nomenclature/review/resync/{p.id}",
        data={"csrf_token": CSRF_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.expire_all()
    assert db_session.query(Sale).first().sku == "НОВЫЙ-SKU"


def test_product_edit_shows_drift_plasha(admin_client, db_session):
    p = _product(db_session, "Сарма 360", "Ваниль", sku=" АКТУАЛЬНЫЙ")
    _sale(db_session, p, sku="УСТАРЕЛО")

    resp = admin_client.get(f"/admin/products/edit/{p.id}")
    assert resp.status_code == 200
    assert "Продаж с прежним названием" in resp.text
    assert "/resync-sales" in resp.text
