import asyncio
import threading

import httpx
import pandas as pd
import pytest

from app.main import app
from app.models import EventLog, Sale
from app.product_parser import ProductMatcher, match_product_by_flavor
from app.services import import_service
from tests.test_import_xlsx import CSRF_TOKEN, XLSX_MIME, make_product
from tests.test_product_parser import make_product as catalog_product


def frame(count):
    return pd.DataFrame(
        [
            {
                "Месяц": "2026-01-01",
                "Тип": "HoReCa",
                "Клиент": f"Клиент {i % 10}",
                "Номенклатура": 'Табак для кальяна "SL" Малина 120г.',
                "SKU": f"RAW-{i}",
                "Количество": 2,
                "Вес": 0.24,
            }
            for i in range(count)
        ]
    )


def test_prepared_matcher_preserves_exact_fuzzy_and_duplicate_rules():
    products = [
        catalog_product("SL", "Малина"),
        catalog_product("Другой", "Малина"),
        catalog_product("SL", "Клубничная содовая"),
        catalog_product("SL", "Манго"),
    ]
    matcher = ProductMatcher(products)
    for name in [
        'Табак для кальяна "SL" Малина 120г.',
        'Табак для кальяна "SL" Клубничн содовая 50g',
        "Манго",
        "Неизвестный товар",
        "",
        "Ёлка",
        "Малина (2.0)",
    ]:
        assert matcher.match(name) == match_product_by_flavor(name, products)
    assert ProductMatcher([]).match("Малина") == (None, 0)


def test_repeated_names_match_once_per_import(db_session, admin_user, monkeypatch):
    make_product(db_session, "SL", "Малина")
    original = ProductMatcher._match
    calls = []

    def match(self, raw):
        calls.append(raw)
        return original(self, raw)

    monkeypatch.setattr(ProductMatcher, "_match", match)
    monkeypatch.setattr(import_service, "IMPORT_BATCH_SIZE", 2)
    assert import_service.import_sales(
        db_session, frame(5), "Тестоград", admin_user.id
    ) == (5, 0)
    assert len(calls) == 1
    sales = db_session.query(Sale).order_by(Sale.id).all()
    assert [row.raw_sku for row in sales] == [f"RAW-{i}" for i in range(5)]
    assert sum(row.qty for row in sales) == 10
    assert sum(row.weight for row in sales) == pytest.approx(1.2)
    assert db_session.query(EventLog).one().rows_imported == 5


def test_log_failure_rolls_back_all_sale_batches(db_session, admin_user, monkeypatch):
    monkeypatch.setattr(import_service, "IMPORT_BATCH_SIZE", 2)
    original = import_service.log_import

    def fail_log(db, **kwargs):
        original(db, **kwargs)
        db.flush()
        raise RuntimeError("simulated failure after inserting log")

    monkeypatch.setattr(import_service, "log_import", fail_log)
    with pytest.raises(RuntimeError):
        import_service.import_sales(db_session, frame(5), "Тестоград", admin_user.id)
    assert db_session.query(Sale).count() == 0
    assert db_session.query(EventLog).count() == 0


def test_slow_excel_does_not_block_other_requests(admin_client, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def read_excel(*args, **kwargs):
        started.set()
        if not release.wait(timeout=10):
            raise RuntimeError("test release timeout")
        return frame(1)

    monkeypatch.setattr("app.routes.imports.pd.read_excel", read_excel)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            cookies=admin_client.cookies,
        ) as client:
            upload = asyncio.create_task(
                client.post(
                    "/import-xlsx",
                    data={"city": "Тестоград", "csrf_token": CSRF_TOKEN},
                    files={"file": ("import.xlsx", b"test", XLSX_MIME)},
                )
            )
            try:
                assert await asyncio.to_thread(started.wait, 3)
                response = await asyncio.wait_for(client.get("/ready"), timeout=2)
                assert response.status_code == 200
                assert not upload.done()
            finally:
                release.set()
                result = await upload
            assert result.status_code == 200
            assert "Импортировано строк: 1" in result.text

    asyncio.run(scenario())
