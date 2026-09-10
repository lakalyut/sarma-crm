from conftest import signed_init_data


def _make_ambassador(db_session, city, telegram_id, first_name, last_name):
    from app.auth_models import User

    user = User(
        email=f"{telegram_id}@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        city=city,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_product(db_session, flavor, sku, is_new=False):
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
        is_new=is_new,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def test_get_leaderboard_empty_when_no_ambassadors(db_session):
    from app.services.leaderboard_service import get_leaderboard

    assert get_leaderboard(db_session) == []


def test_get_leaderboard_counts_burned_aromas_by_category(db_session):
    from app.models import AbcSegment, ProductAbcRating, Visit, VisitProduct
    from app.services.leaderboard_service import get_leaderboard

    ambassador = _make_ambassador(db_session, "Город 1", 111, "Иван", "Иванов")

    segment = AbcSegment(name="Кальянная", sort_order=0)
    db_session.add(segment)
    db_session.commit()
    db_session.refresh(segment)

    product_a = _make_product(db_session, "Мята", "SKU-A")
    product_b = _make_product(db_session, "Дыня", "SKU-B")
    product_c = _make_product(db_session, "Лимон", "SKU-C")
    # новинка: рейтинг A стоит, но в счётчик A попасть не должна
    product_new = _make_product(db_session, "Кола", "SKU-N", is_new=True)

    for product, category in [
        (product_a, "A"),
        (product_b, "B"),
        (product_c, "C"),
        (product_new, "A"),
    ]:
        db_session.add(
            ProductAbcRating(
                product_id=product.id, segment_id=segment.id, category=category
            )
        )
    db_session.commit()

    # два визита, на обоих — один и тот же аромат A (должно посчитаться как 2)
    for _ in range(2):
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
        db_session.commit()

    # третий визит — B, C и новинка
    visit = Visit(
        ambassador_id=ambassador.id,
        city="Город",
        client="Клиент",
        sale_type="Кальянная",
    )
    db_session.add(visit)
    db_session.commit()
    db_session.refresh(visit)
    for product in (product_b, product_c, product_new):
        db_session.add(VisitProduct(visit_id=visit.id, product_id=product.id))
    db_session.commit()

    rows = get_leaderboard(db_session)

    assert len(rows) == 1
    row = rows[0]
    assert row["ambassador"] == "Иван Иванов"
    assert row["visits"] == 3
    assert row["aromas_total"] == 5  # 2×A + B + C + новинка
    assert row["aromas_a"] == 2  # один аромат на двух визитах = 2
    assert row["aromas_b"] == 1
    assert row["aromas_new"] == 1  # новинка сюда, не в A
    assert "category_a" not in row
    assert "aromas" not in row


def test_get_leaderboard_sorts_by_category_a_then_b_then_visits(db_session):
    from app.models import AbcSegment, ProductAbcRating, Visit, VisitProduct
    from app.services.leaderboard_service import get_leaderboard

    segment = AbcSegment(name="Кальянная", sort_order=0)
    db_session.add(segment)
    db_session.commit()
    db_session.refresh(segment)

    product_a = _make_product(db_session, "Мята", "S-A")
    db_session.add(
        ProductAbcRating(product_id=product_a.id, segment_id=segment.id, category="A")
    )
    db_session.commit()

    many_visits = _make_ambassador(db_session, "Г", 201, "Мало", "Аромат")
    few_a = _make_ambassador(db_session, "Г", 202, "Много", "Аромат")

    # many_visits: 3 визита, ни одного аромата A
    for _ in range(3):
        db_session.add(
            Visit(
                ambassador_id=many_visits.id,
                city="Г",
                client="К",
                sale_type="Кальянная",
            )
        )
    db_session.commit()

    # few_a: 1 визит, но с ароматом A
    v = Visit(ambassador_id=few_a.id, city="Г", client="К", sale_type="Кальянная")
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    db_session.add(VisitProduct(visit_id=v.id, product_id=product_a.id))
    db_session.commit()

    rows = get_leaderboard(db_session)
    assert [r["ambassador"] for r in rows] == ["Много Аромат", "Мало Аромат"]


def test_get_leaderboard_hides_deactivated_ambassador(db_session):
    from app.models import Visit
    from app.services.leaderboard_service import get_leaderboard

    active = _make_ambassador(db_session, "Город", 666, "Илья", "Активов")
    inactive = _make_ambassador(db_session, "Город", 777, "Пётр", "Отключенов")
    inactive.is_active = False
    db_session.commit()

    db_session.add(
        Visit(
            ambassador_id=active.id,
            city="Город",
            client="Клиент",
            sale_type="Кальянная",
        )
    )
    db_session.add(
        Visit(
            ambassador_id=inactive.id,
            city="Город",
            client="Клиент",
            sale_type="Кальянная",
        )
    )
    db_session.commit()

    rows = get_leaderboard(db_session)

    names = {r["ambassador"] for r in rows}
    assert "Илья Активов" in names
    assert "Пётр Отключенов" not in names


def test_get_leaderboard_months_and_filtering(db_session):
    from datetime import UTC, datetime

    from app.models import Visit
    from app.services.leaderboard_service import get_leaderboard, get_leaderboard_months

    ambassador = _make_ambassador(db_session, "Город месяцев", 333, "Анна", "Смирнова")

    db_session.add(
        Visit(
            ambassador_id=ambassador.id,
            city="Город",
            client="Клиент А",
            sale_type="Кальянная",
            created_at=datetime(2026, 5, 10, tzinfo=UTC),
        )
    )
    db_session.add(
        Visit(
            ambassador_id=ambassador.id,
            city="Город",
            client="Клиент Б",
            sale_type="Кальянная",
            created_at=datetime(2026, 6, 5, tzinfo=UTC),
        )
    )
    db_session.commit()

    months = get_leaderboard_months(db_session)
    assert months == ["2026-06-01", "2026-05-01"]

    rows_all = get_leaderboard(db_session)
    assert rows_all[0]["visits"] == 2

    rows_may = get_leaderboard(db_session, selected_months=["2026-05-01"])
    assert rows_may[0]["visits"] == 1


def test_leaderboard_page_rejects_anonymous(client):
    resp = client.get("/leaderboard", follow_redirects=False)
    assert resp.status_code in (302, 401)


def test_leaderboard_page_allows_admin(admin_client):
    resp = admin_client.get("/leaderboard")
    assert resp.status_code == 200


def test_leaderboard_page_filters_by_month(admin_client, db_session):
    from datetime import UTC, datetime

    from app.models import Visit

    oleg = _make_ambassador(db_session, "Город фильтра", 444, "Олег", "Олегов")
    irina = _make_ambassador(db_session, "Город фильтра", 555, "Ирина", "Иринина")

    db_session.add(
        Visit(
            ambassador_id=oleg.id,
            city="Город",
            client="Клиент",
            sale_type="Кальянная",
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
    )
    db_session.add(
        Visit(
            ambassador_id=irina.id,
            city="Город",
            client="Клиент",
            sale_type="Кальянная",
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    db_session.commit()

    # Оба месяца реально есть в all_months (иначе пикер их и не предложит) —
    # фильтр должен по-настоящему сужать счётчики визитов. Список амбассадоров
    # в лидерборде не сокращается фильтром (показаны все, даже с 0 визитами
    # за период — тот же принцип, что и в get_leaderboard без фильтра), важна
    # именно цифра «Визиты» у каждого.
    def _row(text, name):
        start = text.index(f"<td>{name}</td>")
        return text[start : text.index("</tr>", start)]

    resp = admin_client.get("/leaderboard?months=2026-05-01")
    assert resp.status_code == 200
    assert "<td>1</td>" in _row(resp.text, "Олег Олегов")  # 1 визит в мае
    assert "<td>1</td>" not in _row(resp.text, "Ирина Иринина")  # 0 визитов

    resp = admin_client.get("/leaderboard?months=2026-06-01")
    assert resp.status_code == 200
    assert "<td>1</td>" not in _row(resp.text, "Олег Олегов")
    assert "<td>1</td>" in _row(resp.text, "Ирина Иринина")


def test_ambassador_app_leaderboard_matches_service(db_session, client):
    ambassador = _make_ambassador(db_session, "Город 2", 222, "Пётр", "Петров")

    init_data = signed_init_data(ambassador.telegram_id)
    resp = client.get(
        "/ambassador/app/leaderboard", headers={"Authorization": f"tma {init_data}"}
    )

    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["ambassador"] == "Пётр Петров"
    assert rows[0]["visits"] == 0
