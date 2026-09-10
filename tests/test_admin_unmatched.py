"""Ручная доводка несопоставленных строк продаж на /admin/unmatched."""

from conftest import CSRF_TOKEN


def _product(db_session, brand="Сарма", flavor="Мята", sku="SARMA-MYATA", w=25):
    from app.models import Product

    p = Product(
        category="Табак",
        brand=brand,
        flavor=flavor,
        canonical_sku=sku,
        canonical_name=f"{brand} {flavor}",
        norm_brand=brand.lower(),
        norm_flavor=flavor.lower(),
        default_weight_g=w,
        is_active=True,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def _unmatched_sale(db_session, raw_name="Табак Сарма Мята 25г", city="Иркутск"):
    from app.models import Sale

    s = Sale(
        city=city,
        month="2026-09-01",
        type="HoReCa",
        client="Кафе А",
        raw_name=raw_name,
        raw_sku="RAW-1",
        qty=3,
        weight=75,
        matched=False,
    )
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_unmatched_list_renders(admin_client, db_session):
    _product(db_session)
    sale = _unmatched_sale(db_session)

    resp = admin_client.get("/admin/unmatched")
    assert resp.status_code == 200
    assert sale.raw_name in resp.text
    assert 'id="unmatched-products"' in resp.text  # datalist товаров
    assert f"/admin/unmatched/{sale.id}/match" in resp.text


def test_match_sale_to_product_moves_it_into_sales(admin_client, db_session):
    from app.models import Sale

    product = _product(db_session, flavor="Дыня", sku="SARMA-DYNYA", w=25)
    sale = _unmatched_sale(db_session, raw_name="Табак Сарма Дыня 50г")

    resp = admin_client.post(
        f"/admin/unmatched/{sale.id}/match",
        data={"csrf_token": CSRF_TOKEN, "product_id": product.id},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.expire_all()
    updated = db_session.get(Sale, sale.id)
    assert updated.matched is True
    assert updated.product_id == product.id
    assert updated.sku == "SARMA-DYNYA"
    # вес из сырого названия («50г»), а не дефолтный товара
    assert "50" in updated.name


def test_delete_unmatched_row(admin_client, db_session):
    from app.models import Sale

    sale = _unmatched_sale(db_session)

    resp = admin_client.post(
        f"/admin/unmatched/{sale.id}/delete",
        data={"csrf_token": CSRF_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.expunge_all()
    assert db_session.query(Sale).filter(Sale.id == sale.id).first() is None


def test_unmatched_edit_updates_fields_and_matches(admin_client, db_session):
    from app.models import Sale

    product = _product(db_session)
    sale = _unmatched_sale(db_session)

    resp = admin_client.post(
        f"/admin/unmatched/{sale.id}/edit",
        data={
            "csrf_token": CSRF_TOKEN,
            "city": "Ангарск",
            "month": "2026-09-01",
            "sale_type": "Розница",
            "client": "Магазин Б",
            "qty": "7",
            "weight": "175",
            "product_id": product.id,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    db_session.expire_all()
    updated = db_session.get(Sale, sale.id)
    assert updated.city == "Ангарск"
    assert updated.type == "Розница"
    assert updated.client == "Магазин Б"
    assert updated.qty == 7
    assert updated.matched is True
    assert updated.product_id == product.id


def test_unmatched_edit_without_product_stays_unmatched(admin_client, db_session):
    from app.models import Sale

    sale = _unmatched_sale(db_session)

    admin_client.post(
        f"/admin/unmatched/{sale.id}/edit",
        data={
            "csrf_token": CSRF_TOKEN,
            "city": "Иркутск",
            "month": "2026-09-01",
            "sale_type": "HoReCa",
            "client": "Кафе А",
            "qty": "3",
            "weight": "75",
            "product_id": "",
        },
    )
    db_session.expire_all()
    assert db_session.get(Sale, sale.id).matched is False


def test_unmatched_forbidden_for_non_admin(client, db_session):
    from app.auth_models import SessionModel, User, default_expiry, new_session_id

    sale = _unmatched_sale(db_session)
    user = User(email="analyst-um@example.com", role="user", is_active=True)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    sid = new_session_id()
    db_session.add(
        SessionModel(id=sid, user_id=user.id, expires_at=default_expiry(hours=1))
    )
    db_session.commit()
    client.cookies.set("session_id", sid)

    resp = client.get("/admin/unmatched", follow_redirects=False)
    assert resp.status_code == 403
    resp = client.post(
        f"/admin/unmatched/{sale.id}/delete",
        data={"csrf_token": CSRF_TOKEN},
        follow_redirects=False,
    )
    assert resp.status_code == 403
