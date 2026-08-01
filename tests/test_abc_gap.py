from app.models import AbcSegment, Product, ProductAbcRating, Sale
from app.product_parser import normalize_text
from app.services.abc_service import get_client_abc_overview


def make_segment(db_session, name="HoReCa"):
    segment = AbcSegment(name=name, sort_order=0)
    db_session.add(segment)
    db_session.commit()
    db_session.refresh(segment)
    return segment.id


def make_product(db_session, brand, flavor, is_active=True):
    canonical_sku = f'Табак для кальяна "{brand}" {flavor}'
    product = Product(
        category="Табак для кальяна",
        brand=brand,
        flavor=flavor,
        canonical_sku=canonical_sku,
        canonical_name=canonical_sku,
        default_weight_g=120,
        norm_brand=normalize_text(brand),
        norm_flavor=normalize_text(flavor),
        is_active=is_active,
        is_new=False,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product.id


def rate(db_session, product_id, segment_id, category):
    db_session.add(
        ProductAbcRating(
            product_id=product_id, segment_id=segment_id, category=category
        )
    )
    db_session.commit()


def make_sale(db_session, city, client, sale_type, product_id, month="2026-01-01"):
    db_session.add(
        Sale(
            city=city,
            month=month,
            type=sale_type,
            client=client,
            raw_name="x",
            raw_sku="x",
            product_id=product_id,
            qty=1,
            weight=0.1,
            matched=True,
        )
    )
    db_session.commit()


def test_client_abc_overview_splits_owned_vs_missing(db_session):
    segment_id = make_segment(db_session)

    a_owned = make_product(db_session, "SL", "A Owned")
    a_missing = make_product(db_session, "SL", "A Missing")
    b_missing_1 = make_product(db_session, "SL", "B Missing 1")
    b_missing_2 = make_product(db_session, "SL", "B Missing 2")
    c_owned = make_product(db_session, "SL", "C Owned")

    for product_id, category in [
        (a_owned, "A"),
        (a_missing, "A"),
        (b_missing_1, "B"),
        (b_missing_2, "B"),
        (c_owned, "C"),
    ]:
        rate(db_session, product_id, segment_id, category)

    make_sale(db_session, "Москва", "Клиент 1", "HoReCa", a_owned)
    make_sale(db_session, "Москва", "Клиент 1", "HoReCa", c_owned)

    overview = get_client_abc_overview(
        db_session,
        city="Москва",
        client="Клиент 1",
        sale_type="HoReCa",
        segment_id=segment_id,
    )

    assert overview["owned_by_category"] == {"A": 1, "B": 0, "C": 1}
    assert overview["total_by_category"] == {"A": 2, "B": 2, "C": 1}

    missing_a = {p.flavor for p in overview["missing_by_category"]["A"]}
    missing_b = {p.flavor for p in overview["missing_by_category"]["B"]}
    missing_c = {p.flavor for p in overview["missing_by_category"]["C"]}

    assert missing_a == {"A Missing"}
    assert missing_b == {"B Missing 1", "B Missing 2"}
    assert missing_c == set()


def test_client_abc_overview_ignores_other_clients_and_types(db_session):
    segment_id = make_segment(db_session)
    product_id = make_product(db_session, "SL", "Общий вкус")
    rate(db_session, product_id, segment_id, "A")

    # тот же товар куплен другим клиентом и другим типом точки этого же клиента —
    # ни то, ни другое не должно засчитываться как "уже есть у клиента"
    make_sale(db_session, "Москва", "Другой клиент", "HoReCa", product_id)
    make_sale(db_session, "Москва", "Клиент 1", "Розница", product_id)

    overview = get_client_abc_overview(
        db_session,
        city="Москва",
        client="Клиент 1",
        sale_type="HoReCa",
        segment_id=segment_id,
    )

    assert overview["owned_by_category"]["A"] == 0
    assert {p.flavor for p in overview["missing_by_category"]["A"]} == {"Общий вкус"}


def test_client_abc_overview_excludes_inactive_products_from_missing_list(db_session):
    segment_id = make_segment(db_session)
    inactive_id = make_product(db_session, "SL", "Снят с продажи", is_active=False)
    rate(db_session, inactive_id, segment_id, "A")

    overview = get_client_abc_overview(
        db_session,
        city="Москва",
        client="Клиент 1",
        sale_type="HoReCa",
        segment_id=segment_id,
    )

    # рейтинг всё равно учтён в счётчиках сегмента...
    assert overview["total_by_category"]["A"] == 1
    assert overview["owned_by_category"]["A"] == 0
    # ...но неактивный товар не предлагается как "чего не хватает"
    assert overview["missing_by_category"]["A"] == []
