"""Горизонт 13.5, доп. заход — вкладки «Анализ визита» / «Эффективность визита»
показывают визиты месяца, за который импорта Sale ещё нет: пикер периода и
список клиентов дополняются из Visit."""

from datetime import UTC, datetime


def _seed(db_session):
    from app.auth_models import User
    from app.models import Product, Sale, Visit, VisitProduct

    amb = User(
        email="backfill-amb@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=910001,
        first_name="Гео",
        last_name="Полев",
        city="Тбилиси",
    )
    db_session.add(amb)

    product = Product(
        category="Табак",
        brand="Сарма",
        flavor="Мята",
        canonical_sku="SKU-M",
        canonical_name="Сарма Мята",
        norm_brand="сарма",
        norm_flavor="мята",
        is_active=True,
    )
    db_session.add(product)

    # продажи есть только за июнь и только по «Кафе Июнь»
    db_session.add(
        Sale(
            city="Тбилиси",
            month="2026-06-01",
            type="Кальянная",
            client="Кафе Июнь",
            product_id=None,
            qty=1,
            weight=1,
        )
    )
    db_session.commit()
    db_session.refresh(amb)
    db_session.refresh(product)

    # визит — в сентябре, по клиенту, которого нет в Sale
    visit = Visit(
        ambassador_id=amb.id,
        city="Тбилиси",
        client="Бар Сентябрь",
        sale_type="Кальянная",
        created_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
        sku_classic=3,
        sku_strong=2,
        sku_light=1,
        people_count=10,
        goal="прокур",
        comment="СЕНТЯБРЬСКАЯ-ЗАМЕТКА",
    )
    db_session.add(visit)
    db_session.commit()
    db_session.refresh(visit)
    db_session.add(VisitProduct(visit_id=visit.id, product_id=product.id))
    db_session.commit()
    return visit


def test_get_visit_months_and_clients(db_session):
    from app.services.ambassador_service import get_visit_clients, get_visit_months

    _seed(db_session)
    assert get_visit_months(db_session, "Тбилиси") == ["2026-09-01"]
    assert get_visit_clients(db_session, "Тбилиси") == ["Бар Сентябрь"]


def test_visit_analysis_tab_offers_visit_only_month(admin_client, db_session):
    _seed(db_session)

    # явно выбираем сентябрь — раньше он выпадал из raw_selected_months,
    # т.к. all_months строился только из Sale (июнь)
    resp = admin_client.get(
        "/analytics/client-analysis?tab=visit_analysis"
        "&city=%D0%A2%D0%B1%D0%B8%D0%BB%D0%B8%D1%81%D0%B8&months=2026-09-01"
    )
    assert resp.status_code == 200
    assert "СЕНТЯБРЬСКАЯ-ЗАМЕТКА" in resp.text
    # месяц-опция сентября есть в пикере
    assert 'value="2026-09-01"' in resp.text


def test_visit_effectiveness_tab_shows_visit_only_month(admin_client, db_session):
    _seed(db_session)

    # без фильтра по месяцам: normalize подставляет все месяцы (теперь включая
    # сентябрь визита), клиент визита появляется в отчёте
    resp = admin_client.get(
        "/analytics/client-analysis?tab=visit_effectiveness"
        "&city=%D0%A2%D0%B1%D0%B8%D0%BB%D0%B8%D1%81%D0%B8"
    )
    assert resp.status_code == 200
    assert "Бар Сентябрь" in resp.text
