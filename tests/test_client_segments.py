from datetime import date

import pytest

from app.models import Sale
from app.services.client_segments_service import build_client_segments


def add_sales(db, client, weights, start=5, city="СПБ", sale_type="HoReCa"):
    for offset, weight in enumerate(weights):
        db.add(
            Sale(
                city=city,
                client=client,
                type=sale_type,
                month=f"2026-{start + offset:02d}-01",
                weight=weight,
                qty=1,
            )
        )
    db.commit()


def report(db, **kwargs):
    return build_client_segments(db, "СПБ", today=date(2026, 11, 9), **kwargs)


def test_abc_boundaries_and_dominant_client(db_session):
    for name, weight in [("A", 80), ("B", 15), ("C", 5)]:
        add_sales(db_session, name, [weight] * 6)
    data = report(db_session, complete=True)
    assert [row["abc"] for row in data["rows"]] == ["A", "B", "C"]
    assert [row["xyz"] for row in data["rows"]] == ["X"] * 3
    assert sum(cell["count"] for cell in data["matrix"].values()) == 3
    add_sales(db_session, "Giant", [1000] * 6)
    assert report(db_session)["rows"][0]["abc"] == "A"


@pytest.mark.parametrize(
    "active,expected", [(6, "X"), (5, "X"), (4, "Y"), (3, "Y"), (2, "Z"), (1, "Z")]
)
def test_presence_thresholds_count_months_not_volume(db_session, active, expected):
    add_sales(db_session, "Client", [10] + [10] * (active - 1) + [0] * (6 - active))
    # Multiple lines in the same month still count as one purchase month.
    add_sales(db_session, "Client", [990], start=5)
    row = report(db_session, complete=True, mode="presence")["rows"][0]
    assert row["active_months"] == active
    assert row["regularity"] == pytest.approx(active / 6 * 100)
    assert row["xyz"] == expected
    assert row["cv"] is None


def test_presence_preserves_abc_and_data_quality_rules(db_session):
    add_sales(db_session, "Variable", [1, 2, 3, 10, 50, 100])
    add_sales(db_session, "Old", [5], start=1)
    add_sales(db_session, "Recent", [10, 10], start=9)
    volume = report(db_session, complete=True)
    presence = report(db_session, complete=True, mode="presence")
    assert [(r["client"], r["abc"], r["share"]) for r in volume["rows"]] == [
        (r["client"], r["abc"], r["share"]) for r in presence["rows"]
    ]
    assert presence["rows"][0]["xyz"] == "X"
    assert volume["rows"][0]["xyz"] == "Z"
    assert presence["reasons"] == {"insufficient": 1, "inactive": 1}
    assert report(db_session, mode="presence")["rows"][0]["reason"] == "unconfirmed"
    db_session.query(Sale).filter(Sale.month == "2026-07-01").delete()
    db_session.commit()
    assert (
        report(db_session, complete=True, mode="presence")["rows"][0]["reason"]
        == "missing"
    )


@pytest.mark.parametrize("active,expected", [(10, "X"), (9, "Y"), (6, "Y"), (5, "Z")])
def test_presence_twelve_month_window(db_session, active, expected):
    for index in range(12):
        year, month = divmod(2025 * 12 + 10 + index, 12)
        db_session.add(
            Sale(
                city="СПБ",
                client="Client",
                month=f"{year}-{month+1:02d}-01",
                weight=10 if index < active else 0,
                qty=1,
            )
        )
    db_session.commit()
    row = report(db_session, length=12, complete=True, mode="presence")["rows"][0]
    assert row["xyz"] == expected
    assert row["active_months"] == active


def test_missing_client_months_are_zeros_but_missing_city_month_blocks_xyz(db_session):
    add_sales(db_session, "Steady", [10] * 6)
    add_sales(db_session, "Intermittent", [20, 0, 20, 0, 20, 0])
    data = report(db_session, complete=True)
    intermittent = next(row for row in data["rows"] if row["client"] == "Intermittent")
    assert intermittent["xyz"] == "Z"
    assert intermittent["cv"] == pytest.approx(100)
    assert intermittent["active_months"] == 3
    db_session.query(Sale).filter(Sale.month == "2026-07-01").delete()
    db_session.commit()
    data = report(db_session, complete=True)
    assert data["missing"] == ["2026-07"]
    assert all(
        row["xyz"] is None and row["reason"] == "missing" for row in data["rows"]
    )


def test_fullness_confirmation_short_history_and_inactive(db_session):
    add_sales(db_session, "Steady", [10] * 6)
    add_sales(db_session, "Recent", [10, 10], start=9)
    add_sales(db_session, "Old", [5], start=1)
    data = report(db_session)
    assert data["reasons"] == {"unconfirmed": 1, "insufficient": 1, "inactive": 1}
    assert data["active_clients"] == 2
    assert all(row["xyz"] is None for row in data["rows"])
    data = report(db_session, complete=True)
    assert data["matrix"]["AX"]["count"] == 1


def test_mixed_month_formats_types_returns_and_current_month(db_session):
    add_sales(db_session, "Same", [10] * 6)
    db_session.add(
        Sale(
            city="СПБ",
            client="Same",
            type="Розница",
            month="Май 2026",
            weight=10,
            qty=1,
        )
    )
    db_session.add(
        Sale(city="СПБ", client="Same", month="2026-06-01", weight=-5, qty=-1)
    )
    db_session.add(
        Sale(city="СПБ", client="Same", month="2026-07-01", weight=5, qty=-1)
    )
    db_session.add(
        Sale(city="СПБ", client="Same", month="2026-11-01", weight=1000, qty=1)
    )
    add_sales(db_session, "Other city", [900] * 6, city="Москва")
    db_session.commit()
    data = report(db_session, complete=True)
    assert data["end"] == "2026-10"
    assert data["total_volume"] == 70
    assert len(data["rows"]) == 1
    assert data["rows"][0]["monthly"] == [20, 10, 10, 10, 10, 10]
    assert data["returns"] == 2


def test_invalid_month_disables_xyz(db_session):
    add_sales(db_session, "Same", [10] * 6)
    db_session.add(Sale(city="СПБ", client="Same", month="bad-month", weight=10, qty=1))
    db_session.commit()
    data = report(db_session, complete=True)
    assert data["invalid_months"] == 1
    assert data["rows"][0]["reason"] == "invalid"


def test_type_filter_recalculates_classes_and_shares(db_session):
    add_sales(db_session, "Cafe", [40] * 6)
    add_sales(db_session, "Small cafe", [10] * 6)
    add_sales(db_session, "Shop", [360] * 6, sale_type="Розница")
    all_rows = {row["client"]: row for row in report(db_session)["rows"]}
    assert all_rows["Cafe"]["abc"] == "B"
    data = report(db_session, complete=True, sale_type="HoReCa")
    assert data["total_volume"] == 300
    assert [row["client"] for row in data["rows"]] == ["Cafe", "Small cafe"]
    assert [row["abc"] for row in data["rows"]] == ["A", "B"]
    assert [row["share"] for row in data["rows"]] == [80, 20]


def test_type_without_sales_in_city_month_is_zero_not_missing(db_session):
    add_sales(db_session, "Shop", [20] * 6, sale_type="Розница")
    add_sales(db_session, "Cafe", [20, 0, 20, 0, 20, 0])
    db_session.query(Sale).filter(Sale.type == "HoReCa", Sale.weight == 0).delete()
    db_session.commit()
    data = report(db_session, complete=True, sale_type="HoReCa")
    assert data["missing"] == []
    assert data["rows"][0]["xyz"] == "Z"
    assert data["rows"][0]["monthly"] == [20, 0, 20, 0, 20, 0]


def test_route_preserves_selected_type(admin_client, db_session):
    add_sales(db_session, "Cafe", [20] * 6)
    add_sales(db_session, "Excluded shop", [900] * 6, sale_type="Розница")
    response = admin_client.get(
        "/analytics/clients/abc-xyz?city=СПБ&end=2026-10&sale_type=HoReCa&complete=true"
    )
    assert response.status_code == 200
    assert '<option value="HoReCa" selected>' in response.text
    assert "Доля типа" in response.text
    assert "Excluded shop" not in response.text
    assert (
        admin_client.get(
            "/analytics/clients/abc-xyz?city=СПБ&sale_type=invalid"
        ).status_code
        == 400
    )
    response = admin_client.get(
        "/analytics/clients/abc-xyz?city=СПБ&end=2026-10&sale_type=HoReCa&complete=true&mode=presence"
    )
    assert response.status_code == 200
    assert 'data-mode="presence" aria-pressed="true"' in response.text
    assert 'name="mode" value="presence"' in response.text
    assert "Регулярность" in response.text
    assert "Май — октябрь 2026 · HoReCa" in response.text
    assert "<summary>Как считаем ABC и XYZ</summary>" in response.text
    assert "XYZ показывает долю месяцев с положительной отгрузкой" in response.text
    assert "Есть закупка" in response.text
    assert "Excluded shop" not in response.text
    assert (
        admin_client.get("/analytics/clients/abc-xyz?mode=invalid").status_code == 422
    )


def test_options_return_only_selected_city_types(admin_client, db_session):
    add_sales(db_session, "Cafe", [20] * 6)
    add_sales(db_session, "Shop", [20] * 6, city="Москва", sale_type="Розница")
    assert admin_client.get("/api/clients/abc-xyz/options?city=СПБ").json() == {
        "types": ["HoReCa"]
    }
    assert admin_client.get("/api/clients/abc-xyz/options?city=Москва").json() == {
        "types": ["Розница"]
    }
    assert admin_client.get("/api/clients/abc-xyz/options").json() == {"types": []}


def test_route_renders_filters_and_escaped_client_name(admin_client, db_session):
    add_sales(db_session, '<script>alert("x")</script>', [10] * 6)
    response = admin_client.get(
        "/analytics/clients/abc-xyz?city=СПБ&end=2026-10&complete=true"
    )
    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text
    assert 'data-segment="AX"' in response.text
    assert "client_segments.js" in response.text
    assert "client_segments.css" in response.text
    assert "XYZ показывает колебания месячного объёма" in response.text
    assert admin_client.get("/analytics/clients/abc-xyz?length=3").status_code == 400
    assert admin_client.get("/analytics/clients/abc-xyz?end=oops").status_code == 400
    assert admin_client.get("/analytics/clients/abc-xyz?end=2999-01").status_code == 400
    assert admin_client.get("/analytics/clients/abc-xyz").status_code == 200


def test_city_access_is_preserved(client, db_session):
    from app.auth_models import SessionModel, User, UserCity, default_expiry

    add_sales(db_session, "Allowed", [10] * 6)
    add_sales(db_session, "Forbidden", [10] * 6, city="Москва")
    user = User(
        email="segments@test.local", role="ambassador", city="СПБ", is_active=True
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        SessionModel(id="segments-test", user_id=user.id, expires_at=default_expiry())
    )
    db_session.commit()
    client.cookies.set("session_id", "segments-test")
    response = client.get("/analytics/clients/abc-xyz?city=Москва&end=2026-10")
    assert response.status_code == 200
    assert "Allowed" in response.text and "Forbidden" not in response.text
    assert client.get("/api/clients/abc-xyz/options?city=Москва").json() == {
        "types": ["HoReCa"]
    }
    user.role = "brand_ambassador"
    db_session.add(UserCity(user_id=user.id, city="СПБ"))
    db_session.commit()
    assert client.get("/analytics/clients/abc-xyz?city=Москва").status_code == 403
    assert client.get("/api/clients/abc-xyz/options?city=Москва").status_code == 403
