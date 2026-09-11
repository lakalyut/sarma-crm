"""Детализация по клиенту (`/analytics/client`) — карточки «Динамика по
месяцам» и «График» должны показываться и когда в выборке всего 1 месяц
(раньше требовалось >1 — репорт 2026-09-11: «пропала карточка с таблицей
продаж», у клиента был ровно один месяц данных)."""


def _sale(db_session, client, sale_type, month, weight=10.0, city="Иркутск"):
    from app.models import Sale

    db_session.add(
        Sale(
            city=city,
            month=month,
            type=sale_type,
            client=client,
            sku="S-1",
            raw_sku="S-1",
            qty=1,
            weight=weight,
            matched=False,
        )
    )
    db_session.commit()


def test_monthly_dynamics_card_shows_with_single_month(admin_client, db_session):
    _sale(db_session, "Кафе Один Месяц", "HoReCa", "2026-09-01")

    resp = admin_client.get(
        "/analytics/client?city=%D0%98%D1%80%D0%BA%D1%83%D1%82%D1%81%D0%BA"
        "&client=%D0%9A%D0%B0%D1%84%D0%B5%20%D0%9E%D0%B4%D0%B8%D0%BD%20"
        "%D0%9C%D0%B5%D1%81%D1%8F%D1%86&sale_type=HoReCa"
    )
    assert resp.status_code == 200
    assert "Динамика по месяцам" in resp.text
    assert "График" in resp.text
    assert 'id="client-monthly-chart"' in resp.text
