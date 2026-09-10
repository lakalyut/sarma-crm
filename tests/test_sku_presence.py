"""Вкладка «Представленность SKU» на «Аналитике по клиентам»."""


def _product(db_session, flavor, sku, is_new=False):
    from app.models import Product

    p = Product(
        category="Табак",
        brand="Сарма",
        flavor=flavor,
        canonical_sku=sku,
        canonical_name=f"Сарма {flavor}",
        norm_brand="сарма",
        norm_flavor=flavor.lower(),
        is_active=True,
        is_new=is_new,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _sale(
    db_session,
    client,
    sale_type,
    sku,
    city="Иркутск",
    month="2026-09-01",
    qty=1,
    product=None,
):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month=month,
            type=sale_type,
            client=client,
            sku=sku,
            raw_sku=sku,
            product_id=product.id if product else None,
            qty=qty,
            weight=qty * 10,
            matched=product is not None,
        )
    )
    db_session.commit()


def test_get_sku_options_has_abc_and_new_badges(db_session):
    from app.models import AbcSegment, ProductAbcRating
    from app.services.sku_presence_service import get_sku_options

    seg = AbcSegment(name="HoReCa", sort_order=0)
    db_session.add(seg)
    db_session.commit()
    db_session.refresh(seg)

    p_a = _product(db_session, "Мята", "SARMA-MYATA")
    p_new = _product(db_session, "Кола", "SARMA-COLA", is_new=True)
    db_session.add(ProductAbcRating(product_id=p_a.id, segment_id=seg.id, category="A"))
    db_session.commit()

    _sale(db_session, "Кафе А", "HoReCa", "SARMA-MYATA", product=p_a)
    _sale(db_session, "Кафе А", "HoReCa", "SARMA-COLA", product=p_new)

    opts = {o["sku"]: o for o in get_sku_options(db_session, "Иркутск", seg.id)}
    assert opts["SARMA-MYATA"]["abc"] == "A"
    assert opts["SARMA-MYATA"]["is_new"] is False
    assert opts["SARMA-COLA"]["is_new"] is True
    assert opts["SARMA-COLA"]["abc"] is None


def test_get_sku_options_includes_new_product_without_sales(db_session):
    """Только что заведённая номенклатура без продаж в этом городе должна
    быть в списке (репорт: «нет номенклатуры, которую недавно добавил»)."""
    from app.services.sku_presence_service import get_sku_options

    _product(db_session, "Мята", "HAS-SALES")
    _sale(db_session, "Кафе А", "HoReCa", "HAS-SALES")
    _product(db_session, "Новинка Без Продаж", "NO-SALES-YET", is_new=True)

    skus = {o["sku"]: o for o in get_sku_options(db_session, "Иркутск", None)}
    assert "NO-SALES-YET" in skus
    assert skus["NO-SALES-YET"]["is_new"] is True


def test_build_sku_presence_green_if_any_ordered(db_session):
    from app.services.sku_presence_service import build_sku_presence

    _sale(db_session, "Кафе Зелёный", "HoReCa", "S-1")  # взял S-1
    _sale(db_session, "Кафе Красный", "HoReCa", "S-OTHER")  # брал что-то другое

    report = build_sku_presence(
        db_session,
        city="Иркутск",
        selected_months=["2026-09-01"],
        selected_skus=["S-1", "S-2"],
    )
    by_client = {r["client"]: r for r in report["rows"]}

    assert by_client["Кафе Зелёный"]["is_present"] is True
    assert by_client["Кафе Зелёный"]["ordered_count"] == 1
    assert by_client["Кафе Зелёный"]["missing_skus"] == ["S-2"]

    assert by_client["Кафе Красный"]["is_present"] is False
    assert by_client["Кафе Красный"]["ordered_count"] == 0

    # зелёные сверху
    assert report["rows"][0]["client"] == "Кафе Зелёный"
    assert report["present_count"] == 1


def test_sku_presence_row_per_client_type(db_session):
    from app.services.sku_presence_service import build_sku_presence

    _sale(db_session, "Сеть Х", "HoReCa", "S-1")
    _sale(db_session, "Сеть Х", "Розница", "S-OTHER")

    report = build_sku_presence(
        db_session,
        city="Иркутск",
        selected_months=["2026-09-01"],
        selected_skus=["S-1"],
    )
    pairs = {(r["client"], r["sale_type"], r["is_present"]) for r in report["rows"]}
    assert ("Сеть Х", "HoReCa", True) in pairs
    assert ("Сеть Х", "Розница", False) in pairs


def test_sku_presence_zero_qty_not_counted(db_session):
    from app.services.sku_presence_service import build_sku_presence

    _sale(db_session, "Кафе Ноль", "HoReCa", "S-1", qty=0)

    report = build_sku_presence(
        db_session,
        city="Иркутск",
        selected_months=["2026-09-01"],
        selected_skus=["S-1"],
    )
    assert report["rows"][0]["is_present"] is False


def test_sku_presence_tab_renders(admin_client, db_session):
    _sale(db_session, "Кафе Маркер", "HoReCa", "SKU-MARK")

    resp = admin_client.get(
        "/analytics/client-analysis?tab=sku_presence"
        "&city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
        "&months=2026-09-01&skus=SKU-MARK"
    )
    assert resp.status_code == 200
    assert "Представленность SKU" in resp.text
    assert "Кафе Маркер" in resp.text
    assert "/analytics/client?city=" in resp.text
