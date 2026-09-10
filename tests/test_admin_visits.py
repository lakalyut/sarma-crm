"""Горизонт 13.5, доп. заход — админ правит и удаляет визиты."""

from datetime import UTC, datetime

from conftest import CSRF_TOKEN


def _make_sale(db_session, city="Город", client="Кафе А", sale_type="Кальянная"):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month="2026-01-01",
            type=sale_type,
            client=client,
            product_id=None,
            qty=1,
            weight=1,
        )
    )
    db_session.commit()


def _make_product(db_session, flavor="Мята"):
    from app.models import Product

    product = Product(
        category="Табак",
        brand="Сарма",
        flavor=flavor,
        canonical_sku=f"SKU-{flavor}",
        canonical_name=f"Сарма {flavor}",
        norm_brand="сарма",
        norm_flavor=flavor.lower(),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def _make_ambassador(db_session, city="Город"):
    from app.auth_models import User

    user = User(
        email="amb-visit-edit@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=555777,
        first_name="Пётр",
        last_name="Полевой",
        city=city,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _make_visit(db_session, ambassador, product, client="Кафе А"):
    from app.models import Visit, VisitProduct

    visit = Visit(
        ambassador_id=ambassador.id,
        city="Город",
        client=client,
        sale_type="Кальянная",
        created_at=datetime(2026, 5, 10, 14, 30, tzinfo=UTC),
        sku_classic=5,
        sku_strong=3,
        sku_light=2,
        people_count=12,
        goal="ротация",
        comment="старая заметка",
    )
    db_session.add(visit)
    db_session.commit()
    db_session.refresh(visit)
    db_session.add(VisitProduct(visit_id=visit.id, product_id=product.id))
    db_session.commit()
    return visit


def _login(client, db_session, role):
    from app.auth_models import SessionModel, User, default_expiry, new_session_id

    user = User(email=f"{role}-vedit@example.com", role=role, is_active=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    sid = new_session_id()
    db_session.add(
        SessionModel(id=sid, user_id=user.id, expires_at=default_expiry(hours=1))
    )
    db_session.commit()
    client.cookies.set("session_id", sid)
    return client


def test_visit_edit_form_renders(admin_client, db_session):
    _make_sale(db_session)
    product = _make_product(db_session)
    amb = _make_ambassador(db_session)
    visit = _make_visit(db_session, amb, product)

    resp = admin_client.get(f"/admin/visits/{visit.id}/edit")
    assert resp.status_code == 200
    assert "Редактирование визита" in resp.text
    assert "старая заметка" in resp.text
    assert "Пётр Полевой" in resp.text


def test_visit_edit_updates_survey_and_aromas(admin_client, db_session):
    _make_sale(db_session)
    p1 = _make_product(db_session, "Мята")
    p2 = _make_product(db_session, "Дыня")
    amb = _make_ambassador(db_session)
    visit = _make_visit(db_session, amb, p1)

    resp = admin_client.post(
        f"/admin/visits/{visit.id}/edit",
        data={
            "csrf_token": CSRF_TOKEN,
            "client": "Кафе А",
            "sale_type": "Кальянная",
            "product_ids": [p2.id],
            "sku_classic": "9",
            "sku_strong": "8",
            "sku_light": "7",
            "people_count": "20",
            "goal": "обучение",
            "comment": "новая заметка",
            "visit_date": "2026-08-01",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    from app.models import Visit, VisitProduct

    db_session.expire_all()
    updated = db_session.get(Visit, visit.id)
    assert updated.sku_classic == 9
    assert updated.people_count == 20
    assert updated.goal == "обучение"
    assert updated.comment == "новая заметка"
    assert updated.created_at.month == 8
    assert updated.created_at.hour == 14  # время суток сохранено

    product_ids = [
        row[0]
        for row in db_session.query(VisitProduct.product_id).filter(
            VisitProduct.visit_id == visit.id
        )
    ]
    assert product_ids == [p2.id]


def test_visit_edit_rejects_empty_comment(admin_client, db_session):
    _make_sale(db_session)
    product = _make_product(db_session)
    amb = _make_ambassador(db_session)
    visit = _make_visit(db_session, amb, product)

    resp = admin_client.post(
        f"/admin/visits/{visit.id}/edit",
        data={
            "csrf_token": CSRF_TOKEN,
            "client": "Кафе А",
            "sale_type": "Кальянная",
            "product_ids": [product.id],
            "sku_classic": "1",
            "sku_strong": "1",
            "sku_light": "1",
            "people_count": "1",
            "goal": "ротация",
            "comment": "   ",
            "visit_date": "2026-05-10",
        },
    )
    assert resp.status_code == 200
    assert "комментарий" in resp.text.lower()

    from app.models import Visit

    db_session.expire_all()
    assert db_session.get(Visit, visit.id).comment == "старая заметка"


def test_visit_delete_removes_visit_and_products(admin_client, db_session):
    _make_sale(db_session)
    product = _make_product(db_session)
    amb = _make_ambassador(db_session)
    visit = _make_visit(db_session, amb, product)

    resp = admin_client.post(
        f"/admin/visits/{visit.id}/delete",
        data={
            "csrf_token": CSRF_TOKEN,
            "back_url": "/analytics/client-analysis?tab=visit_analysis",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    from app.models import Visit, VisitProduct

    db_session.expunge_all()
    assert db_session.query(Visit).filter(Visit.id == visit.id).first() is None
    assert (
        db_session.query(VisitProduct).filter(VisitProduct.visit_id == visit.id).count()
        == 0
    )


def test_visit_edit_forbidden_for_non_admin(client, db_session):
    _make_sale(db_session)
    product = _make_product(db_session)
    amb = _make_ambassador(db_session)
    visit = _make_visit(db_session, amb, product)

    _login(client, db_session, "user")
    resp = client.get(f"/admin/visits/{visit.id}/edit", follow_redirects=False)
    assert resp.status_code == 403


def test_visit_analysis_tab_shows_admin_actions(admin_client, db_session):
    _make_sale(db_session)
    product = _make_product(db_session)
    amb = _make_ambassador(db_session)
    visit = _make_visit(db_session, amb, product)

    resp = admin_client.get(
        "/analytics/client-analysis?tab=visit_analysis"
        "&city=%D0%93%D0%BE%D1%80%D0%BE%D0%B4"
    )
    assert resp.status_code == 200
    assert f"/admin/visits/{visit.id}/edit" in resp.text
