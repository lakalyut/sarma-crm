from datetime import UTC, datetime


def _ambassador(db_session, telegram_id=777001):
    from app.auth_models import User

    user = User(
        email=f"{telegram_id}@example.com",
        role="ambassador",
        is_active=True,
        telegram_id=telegram_id,
        first_name="Пётр",
        last_name="Полевой",
        city="Город",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _visit(db_session, ambassador, client, created_at, **fields):
    from app.models import Visit

    visit = Visit(
        ambassador_id=ambassador.id,
        city="Город",
        client=client,
        sale_type="Кальянная",
        created_at=created_at,
        sku_classic=fields.get("sku_classic", 5),
        sku_strong=fields.get("sku_strong", 3),
        sku_light=fields.get("sku_light", 2),
        people_count=fields.get("people_count", 12),
        goal=fields.get("goal", "ротация"),
        comment=fields.get("comment", "заметка"),
    )
    db_session.add(visit)
    db_session.commit()
    db_session.refresh(visit)
    return visit


def test_visit_analysis_lists_visits_with_survey(db_session):
    from app.services.visit_analysis_service import get_visit_analysis

    amb = _ambassador(db_session)
    _visit(
        db_session,
        amb,
        "Кафе А",
        datetime(2026, 5, 10, tzinfo=UTC),
        comment="майская заметка",
        goal="первичный завоз",
    )
    _visit(db_session, amb, "Кафе Б", datetime(2026, 8, 1, tzinfo=UTC))

    rows = get_visit_analysis(db_session, "Город", [], [])
    assert len(rows) == 2
    # новые сверху
    assert rows[0]["client"] == "Кафе Б"
    assert rows[1]["comment"] == "майская заметка"
    assert rows[1]["goal"] == "первичный завоз"
    assert rows[1]["sku_classic"] == 5
    assert rows[1]["ambassador"] == "Пётр Полевой"


def test_visit_analysis_filters_by_month_and_client(db_session):
    from app.services.visit_analysis_service import get_visit_analysis

    amb = _ambassador(db_session)
    _visit(db_session, amb, "Кафе А", datetime(2026, 5, 10, tzinfo=UTC))
    _visit(db_session, amb, "Кафе Б", datetime(2026, 8, 1, tzinfo=UTC))

    only_may = get_visit_analysis(db_session, "Город", ["2026-05-01"], [])
    assert [r["client"] for r in only_may] == ["Кафе А"]

    only_b = get_visit_analysis(db_session, "Город", [], ["Кафе Б"])
    assert [r["client"] for r in only_b] == ["Кафе Б"]


def test_visit_analysis_tab_renders(admin_client, db_session):
    amb = _ambassador(db_session)
    _visit(
        db_session,
        amb,
        "Кафе А",
        datetime(2026, 5, 10, tzinfo=UTC),
        comment="ЗАМЕТКА-МАРКЕР",
    )

    resp = admin_client.get(
        "/analytics/client-analysis?tab=visit_analysis&city=%D0%93%D0%BE%D1%80%D0%BE%D0%B4"
    )
    assert resp.status_code == 200
    assert "Анализ визита" in resp.text
    assert "ЗАМЕТКА-МАРКЕР" in resp.text
