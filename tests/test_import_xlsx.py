import io

import pandas as pd

from app.models import EventLog, Product, Sale
from app.product_parser import normalize_text

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def make_product(db_session, brand, flavor, category="Табак для кальяна", weight_g=120):
    canonical_sku = f'{category} "{brand}" {flavor}'
    product = Product(
        category=category,
        brand=brand,
        flavor=flavor,
        canonical_sku=canonical_sku,
        canonical_name=f"{canonical_sku} {weight_g}г.",
        default_weight_g=weight_g,
        norm_brand=normalize_text(brand),
        norm_flavor=normalize_text(flavor),
        is_active=True,
        is_new=False,
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def build_xlsx(rows, columns=None):
    columns = columns or [
        "Месяц",
        "Тип",
        "Клиент",
        "Номенклатура",
        "SKU",
        "Количество",
        "Вес",
    ]
    df = pd.DataFrame(rows, columns=columns)
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    return buf


def test_import_matches_known_product_and_flags_unknown(
    admin_client, db_session, admin_user
):
    product = make_product(db_session, "SL", "Малина")

    rows = [
        {
            "Месяц": "2026-01-01",
            "Тип": "HoReCa",
            "Клиент": "Кальянная Тест",
            "Номенклатура": 'Табак для кальяна "SL" Малина 120г.',
            "SKU": "RAW-SKU-1",
            "Количество": 5,
            "Вес": 0.6,
        },
        {
            "Месяц": "2026-01-01",
            "Тип": "HoReCa",
            "Клиент": "Кальянная Тест",
            "Номенклатура": "Совершенно неизвестный товар без аналогов",
            "SKU": "RAW-SKU-2",
            "Количество": 2,
            "Вес": 0.2,
        },
    ]

    resp = admin_client.post(
        "/import-xlsx",
        data={"city": "Тестоград"},
        files={"file": ("import.xlsx", build_xlsx(rows), XLSX_MIME)},
    )

    assert resp.status_code == 200
    assert "Импортировано строк: 2" in resp.text
    assert "не сопоставлено: 1" in resp.text

    sales = db_session.query(Sale).order_by(Sale.id).all()
    assert len(sales) == 2

    matched_sale = next(s for s in sales if s.raw_sku == "RAW-SKU-1")
    assert matched_sale.matched is True
    assert matched_sale.product_id == product.id
    assert matched_sale.sku == product.canonical_sku
    assert matched_sale.city == "Тестоград"

    unmatched_sale = next(s for s in sales if s.raw_sku == "RAW-SKU-2")
    assert unmatched_sale.matched is False
    assert unmatched_sale.product_id is None

    events = db_session.query(EventLog).all()
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "import"
    assert event.city == "Тестоград"
    assert event.months == "2026-01-01"
    assert event.rows_imported == 2
    assert event.rows_unmatched == 1
    assert event.user_id == admin_user.id


def test_import_requires_admin(client):
    rows = [
        {
            "Месяц": "2026-01-01",
            "Тип": "HoReCa",
            "Клиент": "X",
            "Номенклатура": "Y",
            "SKU": "Z",
            "Количество": 1,
            "Вес": 1,
        }
    ]

    resp = client.post(
        "/import-xlsx",
        data={"city": "Тестоград"},
        files={"file": ("import.xlsx", build_xlsx(rows), XLSX_MIME)},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"


def test_import_missing_required_column_shows_error(admin_client, db_session):
    buf = build_xlsx(
        [
            {
                "Месяц": "2026-01-01",
                "Тип": "HoReCa",
                "Клиент": "X",
                "Номенклатура": "Y",
                "SKU": "Z",
                "Количество": 1,
            }
        ],
        columns=["Месяц", "Тип", "Клиент", "Номенклатура", "SKU", "Количество"],
    )

    resp = admin_client.post(
        "/import-xlsx",
        data={"city": "Тестоград"},
        files={"file": ("import.xlsx", buf, XLSX_MIME)},
    )

    assert resp.status_code == 200
    assert "Нет колонок" in resp.text
    assert "Вес" in resp.text
    assert db_session.query(Sale).count() == 0


def test_import_invalid_file_shows_error(admin_client, db_session):
    resp = admin_client.post(
        "/import-xlsx",
        data={"city": "Тестоград"},
        files={"file": ("import.xlsx", io.BytesIO(b"not an excel file"), XLSX_MIME)},
    )

    assert resp.status_code == 200
    assert "Ошибка чтения XLSX" in resp.text
    assert db_session.query(Sale).count() == 0
