from datetime import UTC, datetime


def _make_ambassador(
    db_session, telegram_id=555000, first_name="Иван", last_name="Иванов"
):
    from app.auth_models import User

    user = User(
        email=f"{telegram_id}@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
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


def _make_visit(
    db_session, ambassador, city, client, sale_type, created_at, product_ids
):
    from app.models import Visit, VisitProduct

    visit = Visit(
        ambassador_id=ambassador.id,
        city=city,
        client=client,
        sale_type=sale_type,
        created_at=created_at,
    )
    db_session.add(visit)
    db_session.commit()
    db_session.refresh(visit)

    for product_id in product_ids:
        db_session.add(VisitProduct(visit_id=visit.id, product_id=product_id))
    db_session.commit()
    return visit


def _make_sale(db_session, city, client, month, product_id):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month=month,
            type="Кальянная",
            client=client,
            product_id=product_id,
            qty=1,
            weight=1,
            matched=True,
        )
    )
    db_session.commit()


def test_ordered_and_not_ordered_flavors(db_session):
    from app.services.visit_effectiveness_service import (
        build_visit_effectiveness_report,
    )

    ambassador = _make_ambassador(db_session)
    ordered_product = _make_product(db_session, "Мята", "SKU-ORD")
    not_ordered_product = _make_product(db_session, "Лимон", "SKU-NOTORD")

    _make_visit(
        db_session,
        ambassador,
        city="Город",
        client="Клиент А",
        sale_type="Кальянная",
        created_at=datetime(2026, 6, 15, tzinfo=UTC),
        product_ids=[ordered_product.id, not_ordered_product.id],
    )
    _make_sale(db_session, "Город", "Клиент А", "2026-06-01", ordered_product.id)

    report = build_visit_effectiveness_report(
        db_session, city="Город", selected_months=["2026-06-01"], selected_clients=[]
    )

    assert len(report["clients"]) == 1
    aromas = {a["flavor"]: a["ordered"] for a in report["clients"][0]["aromas"]}
    assert aromas == {"Мята": True, "Лимон": False}
    ambassadors_for_mint = next(
        a for a in report["clients"][0]["aromas"] if a["flavor"] == "Мята"
    )["ambassadors"]
    assert ambassadors_for_mint == ["Иван Иванов"]


def test_ru_formatted_month_matches_visit_by_year_month(db_session):
    from app.services.visit_effectiveness_service import (
        build_visit_effectiveness_report,
    )

    ambassador = _make_ambassador(db_session, telegram_id=555001)
    product = _make_product(db_session, "Дыня", "SKU-RU")

    _make_visit(
        db_session,
        ambassador,
        city="РуГород",
        client="Клиент Б",
        sale_type="Кальянная",
        created_at=datetime(2026, 6, 10, tzinfo=UTC),
        product_ids=[product.id],
    )

    report = build_visit_effectiveness_report(
        db_session,
        city="РуГород",
        selected_months=["Июнь 2026"],
        selected_clients=[],
    )

    assert len(report["clients"]) == 1
    assert report["clients"][0]["aromas"][0]["flavor"] == "Дыня"


def test_visit_outside_period_excluded(db_session):
    from app.services.visit_effectiveness_service import (
        build_visit_effectiveness_report,
    )

    ambassador = _make_ambassador(db_session, telegram_id=555002)
    product = _make_product(db_session, "Виноград", "SKU-OUT")

    _make_visit(
        db_session,
        ambassador,
        city="Город2",
        client="Клиент В",
        sale_type="Кальянная",
        created_at=datetime(2026, 1, 5, tzinfo=UTC),
        product_ids=[product.id],
    )

    report = build_visit_effectiveness_report(
        db_session, city="Город2", selected_months=["2026-06-01"], selected_clients=[]
    )

    assert report["clients"] == []


def test_selected_clients_narrows_result(db_session):
    from app.services.visit_effectiveness_service import (
        build_visit_effectiveness_report,
    )

    ambassador = _make_ambassador(db_session, telegram_id=555003)
    product = _make_product(db_session, "Персик", "SKU-NAR")

    _make_visit(
        db_session,
        ambassador,
        city="Город3",
        client="Клиент Г",
        sale_type="Кальянная",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        product_ids=[product.id],
    )
    _make_visit(
        db_session,
        ambassador,
        city="Город3",
        client="Клиент Д",
        sale_type="Кальянная",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        product_ids=[product.id],
    )

    report_all = build_visit_effectiveness_report(
        db_session, city="Город3", selected_months=["2026-06-01"], selected_clients=[]
    )
    assert {c["name"] for c in report_all["clients"]} == {"Клиент Г", "Клиент Д"}

    report_narrow = build_visit_effectiveness_report(
        db_session,
        city="Город3",
        selected_months=["2026-06-01"],
        selected_clients=["Клиент Г"],
    )
    assert {c["name"] for c in report_narrow["clients"]} == {"Клиент Г"}


def test_visit_effectiveness_tab_requires_analyst(admin_client):
    resp = admin_client.get(
        "/analytics/client-analysis?tab=visit_effectiveness&city=Город"
    )
    assert resp.status_code == 200
