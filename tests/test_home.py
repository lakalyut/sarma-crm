"""Главная страница (`/`, запрос 2026-09-12): снапшот по всем городам сразу
с плашками года + расчётный ABC (80/15/5 по весу, без новинок) для топа
вкусов + разрез по городам на клике."""


def _product(db_session, flavor, sku, brand="Сарма", is_new=False, is_active=True):
    from app.models import Product

    p = Product(
        category="Табак",
        brand=brand,
        flavor=flavor,
        canonical_sku=sku,
        canonical_name=f"{brand} {flavor}",
        norm_brand=brand.lower(),
        norm_flavor=flavor.lower(),
        is_active=is_active,
        is_new=is_new,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _sale(
    db_session,
    city,
    month,
    weight,
    qty=1,
    client="Кафе А",
    product=None,
    sale_type="HoReCa",
):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month=month,
            type=sale_type,
            client=client,
            product_id=product.id if product else None,
            sku=product.canonical_sku if product else None,
            qty=qty,
            weight=weight,
            matched=product is not None,
        )
    )
    db_session.commit()


def test_get_available_years_sorted_desc(db_session):
    from app.services.home_service import get_available_years

    _sale(db_session, "Иркутск", "2024-03-01", 10)
    _sale(db_session, "Иркутск", "2026-05-01", 10)
    _sale(db_session, "Иркутск", "Март 2025", 10)

    assert get_available_years(db_session) == [2026, 2025, 2024]


def test_get_available_years_empty_db(db_session):
    from app.services.home_service import get_available_years

    assert get_available_years(db_session) == []


def test_compute_abc_ranking_80_15_5():
    from app.services.home_service import compute_abc_ranking

    # 100 всего: A(1)=80, B(2)=15, C(3)=5 — классика 80/15/5
    weights = {1: 80.0, 2: 15.0, 3: 5.0}
    ranking = compute_abc_ranking(weights, new_product_ids=set())

    assert ranking[1] == "A"
    assert ranking[2] == "B"
    assert ranking[3] == "C"


def test_compute_abc_ranking_excludes_new_products():
    from app.services.home_service import compute_abc_ranking

    # новинка (id=2) с большим весом не должна попасть в ranking вообще и
    # не должна раздувать базу для % остальных
    weights = {1: 80.0, 2: 500.0, 3: 20.0}
    ranking = compute_abc_ranking(weights, new_product_ids={2})

    assert 2 not in ranking
    # без учёта новинки база — 100 (80+20): 1 -> 80% -> A, 3 -> 100% -> C
    assert ranking[1] == "A"
    assert ranking[3] == "C"


def test_compute_abc_ranking_empty_when_only_new_products():
    from app.services.home_service import compute_abc_ranking

    ranking = compute_abc_ranking({1: 50.0}, new_product_ids={1})
    assert ranking == {}


def test_home_overview_has_data_false_when_no_sales(db_session):
    from app.services.home_service import get_home_overview

    overview = get_home_overview(db_session, year=None)
    assert overview["has_data"] is False
    assert overview["available_years"] == []


def test_home_overview_top_flavors_and_cities(db_session):
    from app.services.home_service import get_home_overview

    p_a = _product(db_session, "Мята", "S-1")
    p_b = _product(db_session, "Кола", "S-2")
    p_new = _product(db_session, "Новинка", "S-3", is_new=True)

    _sale(db_session, "Иркутск", "2026-03-01", 80, product=p_a)
    _sale(db_session, "Новосибирск", "2026-03-01", 20, product=p_b)
    _sale(db_session, "Иркутск", "2026-03-01", 5, product=p_new)

    overview = get_home_overview(db_session, year=2026)

    assert overview["has_data"] is True
    assert overview["year"] == 2026
    assert overview["metrics"]["weight"] == 105

    flavor_by_name = {r["flavor"]: r for r in overview["top_flavors"]}
    assert flavor_by_name["Мята"]["category"] == "A"
    assert flavor_by_name["Кола"]["category"] is not None
    assert flavor_by_name["Новинка"]["is_new"] is True
    assert flavor_by_name["Новинка"]["category"] is None

    cities = {r["city"]: r for r in overview["top_cities"]}
    assert cities["Иркутск"]["weight"] == 85
    assert cities["Новосибирск"]["weight"] == 20


def test_home_overview_unmatched_sales_excluded_from_flavors(db_session):
    from app.models import Sale
    from app.services.home_service import get_home_overview

    db_session.add(
        Sale(
            city="Иркутск",
            month="2026-03-01",
            type="HoReCa",
            client="Кафе Б",
            product_id=None,
            raw_name="что-то сырое",
            qty=1,
            weight=50,
            matched=False,
        )
    )
    db_session.commit()

    overview = get_home_overview(db_session, year=2026)
    assert overview["top_flavors"] == []
    # но в топ городов и в общий вес несопоставленная продажа всё равно
    # попадает — там ограничения на product_id нет
    assert overview["metrics"]["weight"] == 50


def test_home_overview_year_over_year_delta(db_session):
    from app.services.home_service import get_home_overview

    _sale(db_session, "Иркутск", "2025-03-01", 100)
    _sale(db_session, "Иркутск", "2026-03-01", 150)

    overview = get_home_overview(db_session, year=2026)
    delta = overview["metrics"]["weight_delta"]
    assert delta["direction"] == "up"
    assert delta["pct"] == 50


def test_home_overview_year_over_year_delta_only_elapsed_months(db_session):
    """Прошлый год сравнивается только за ТЕ ЖЕ месяцы, что прожиты в
    текущем — не за весь прошлый год целиком (иначе неполный текущий год
    всегда выглядел бы искусственно просевшим)."""
    from app.services.home_service import get_home_overview

    _sale(db_session, "Иркутск", "2025-03-01", 100)
    _sale(db_session, "Иркутск", "2025-12-01", 900)  # декабрь 2025 — не прожит в 2026
    _sale(db_session, "Иркутск", "2026-03-01", 100)

    overview = get_home_overview(db_session, year=2026)
    delta = overview["metrics"]["weight_delta"]
    # 100 к 100 — 0%, а не 100 к 1000 — не должно быть глубокого падения
    assert delta["pct"] == 0
    assert delta["direction"] == "neutral"


def test_home_overview_no_previous_year_data(db_session):
    from app.services.home_service import get_home_overview

    _sale(db_session, "Иркутск", "2026-03-01", 100)

    overview = get_home_overview(db_session, year=2026)
    delta = overview["metrics"]["weight_delta"]
    assert delta["pct"] is None
    assert delta["direction"] == "neutral"


def test_get_product_abc_by_city(db_session):
    from app.services.home_service import get_product_abc_by_city

    p_a = _product(db_session, "Мята", "S-1")
    _sale(db_session, "Иркутск", "2026-03-01", 80, product=p_a)
    _sale(
        db_session,
        "Иркутск",
        "2026-03-01",
        20,
        product=_product(db_session, "Кола", "S-2"),
    )
    _sale(db_session, "Новосибирск", "2026-03-01", 5, product=p_a)
    _sale(
        db_session,
        "Новосибирск",
        "2026-03-01",
        95,
        product=_product(db_session, "Дыня", "S-3"),
    )

    data = get_product_abc_by_city(db_session, p_a.id, 2026)

    assert data is not None
    assert data["product"].id == p_a.id
    by_city = {r["city"]: r for r in data["rows"]}
    assert by_city["Иркутск"]["category"] == "A"  # 80 из 100 — вся доля
    assert by_city["Новосибирск"]["category"] == "C"  # 5 из 100 — хвост


def test_get_product_abc_by_city_unknown_product(db_session):
    from app.services.home_service import get_product_abc_by_city

    assert get_product_abc_by_city(db_session, 999, 2026) is None


def test_home_page_requires_login(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"


def test_home_page_renders_for_admin(admin_client, db_session):
    p_a = _product(db_session, "Мята", "S-1")
    _sale(db_session, "Иркутск", "2026-03-01", 80, product=p_a)

    resp = admin_client.get("/")
    assert resp.status_code == 200
    assert "Главная" in resp.text or "Мята" in resp.text


def test_home_page_empty_state_when_no_sales(admin_client):
    resp = admin_client.get("/")
    assert resp.status_code == 200


def test_ambassador_root_redirects_to_clients(client, db_session):
    # логин через /auth/login в тестах не используется нигде в проекте —
    # secure=True на session_id cookie не проходит через TestClient (тот же
    # приём, что admin_client в conftest.py: сессия заводится в БД напрямую,
    # cookie выставляется вручную).
    from app.auth_models import SessionModel, User, default_expiry, new_session_id

    user = User(
        email="amb@example.com",
        role="ambassador",
        is_active=True,
        city="Иркутск",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    sid = new_session_id()
    db_session.add(
        SessionModel(id=sid, user_id=user.id, expires_at=default_expiry(hours=1))
    )
    db_session.commit()
    client.cookies.set("session_id", sid)

    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/analytics/clients"


def test_product_abc_page_requires_analyst(client):
    resp = client.get("/analytics/product-abc?product_id=1", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"


def test_product_abc_page_404_for_unknown_product(admin_client):
    resp = admin_client.get("/analytics/product-abc?product_id=999999")
    assert resp.status_code == 404


def test_product_abc_page_renders(admin_client, db_session):
    p_a = _product(db_session, "Мята", "S-1")
    _sale(db_session, "Иркутск", "2026-03-01", 80, product=p_a)

    resp = admin_client.get(f"/analytics/product-abc?product_id={p_a.id}&year=2026")
    assert resp.status_code == 200
    assert "Мята" in resp.text
    assert "Иркутск" in resp.text
