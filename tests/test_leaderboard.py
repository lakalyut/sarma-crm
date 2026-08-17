from conftest import signed_init_data


def _make_ambassador(db_session, region, telegram_id, first_name, last_name):
    from app.auth_models import User

    user = User(
        email=f"{telegram_id}@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        region_id=region.id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_product(db_session, flavor, sku):
    from app.models import Product

    product = Product(
        category="Табак",
        brand="Бренд",
        flavor=flavor,
        canonical_sku=sku,
        canonical_name=f"Бренд {flavor}",
        norm_brand="бренд",
        norm_flavor=flavor.lower(),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def test_get_leaderboard_empty_when_no_ambassadors(db_session):
    from app.services.leaderboard_service import get_leaderboard

    assert get_leaderboard(db_session) == []


def test_get_leaderboard_counts_visits_and_category_a(db_session):
    from app.models import AbcSegment, ProductAbcRating, Region, Visit, VisitProduct
    from app.services.leaderboard_service import get_leaderboard

    region = Region(name="Регион 1", sort_order=0)
    db_session.add(region)
    db_session.commit()
    db_session.refresh(region)

    ambassador = _make_ambassador(db_session, region, 111, "Иван", "Иванов")

    segment = AbcSegment(name="Кальянная", sort_order=0)
    db_session.add(segment)
    db_session.commit()
    db_session.refresh(segment)

    product_a = _make_product(db_session, "Мята", "SKU-A")
    product_c = _make_product(db_session, "Лимон", "SKU-C")

    db_session.add(
        ProductAbcRating(product_id=product_a.id, segment_id=segment.id, category="A")
    )
    db_session.add(
        ProductAbcRating(product_id=product_c.id, segment_id=segment.id, category="C")
    )
    db_session.commit()

    visit = Visit(
        ambassador_id=ambassador.id,
        city="Город",
        client="Клиент",
        sale_type="Кальянная",
    )
    db_session.add(visit)
    db_session.commit()
    db_session.refresh(visit)

    db_session.add(VisitProduct(visit_id=visit.id, product_id=product_a.id))
    db_session.add(VisitProduct(visit_id=visit.id, product_id=product_c.id))
    db_session.commit()

    rows = get_leaderboard(db_session)

    assert len(rows) == 1
    row = rows[0]
    assert row["ambassador"] == "Иван Иванов"
    assert row["region"] == "Регион 1"
    assert row["visits"] == 1
    assert row["category_a"] == 1
    assert row["aromas"] == ["Лимон", "Мята"]


def test_leaderboard_page_rejects_anonymous(client):
    resp = client.get("/leaderboard", follow_redirects=False)
    assert resp.status_code in (302, 401)


def test_leaderboard_page_allows_admin(admin_client):
    resp = admin_client.get("/leaderboard")
    assert resp.status_code == 200


def test_ambassador_app_leaderboard_matches_service(db_session, client):
    from app.models import Region

    region = Region(name="Регион 2", sort_order=0)
    db_session.add(region)
    db_session.commit()
    db_session.refresh(region)

    ambassador = _make_ambassador(db_session, region, 222, "Пётр", "Петров")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/leaderboard", headers={"Authorization": f"tma {init_data}"}
    )

    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["ambassador"] == "Пётр Петров"
    assert rows[0]["visits"] == 0
