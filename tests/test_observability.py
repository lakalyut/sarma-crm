import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import engine, get_db
from app.main import app
from app.observability import RequestMetricsMiddleware
from tests.test_import_xlsx import CSRF_TOKEN, XLSX_MIME, build_xlsx


def records(caplog, event):
    return [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "uvicorn.error.pulse"
        and json.loads(record.message)["event"] == event
    ]


def test_concurrent_sync_sql_counts_are_isolated(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    test_app = FastAPI()
    test_app.add_middleware(RequestMetricsMiddleware)
    barrier = threading.Barrier(2)

    @test_app.get("/measure/{count}")
    def measure(count: int):
        barrier.wait(timeout=5)
        with engine.connect() as conn:
            for _ in range(count):
                conn.execute(text("SELECT :value"), {"value": "private-value"})
        return {"ok": True}

    def call(count):
        with TestClient(test_app) as client:
            return client.get(f"/measure/{count}?token=private-token")

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(call, (2, 5)))
    assert all(response.status_code == 200 for response in responses)
    logs = records(caplog, "http_request")
    assert sorted(record["sql_count"] for record in logs) == [2, 5]
    assert len({record["request_id"] for record in logs}) == 2
    assert all(record["route"] == "/measure/{count}" for record in logs)
    assert all(
        record["duration_ms"] >= record["sql_duration_ms"] >= 0 for record in logs
    )
    assert all(record["response_bytes"] > 0 for record in logs)
    assert "private-value" not in caplog.text
    assert "private-token" not in "".join(
        record.message
        for record in caplog.records
        if record.name == "uvicorn.error.pulse"
    )


def test_failed_sql_is_counted_and_next_request_is_clean(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    test_app = FastAPI()
    test_app.add_middleware(RequestMetricsMiddleware)

    @test_app.get("/fail")
    def fail():
        with engine.connect() as conn:
            conn.execute(text("SELECT * FROM nonexistent_metrics_test_table"))

    @test_app.get("/ok")
    def ok():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True}

    with TestClient(test_app, raise_server_exceptions=False) as client:
        assert client.get("/fail").status_code == 500
        assert client.get("/ok").status_code == 200
    logs = records(caplog, "http_request")
    assert [(row["status"], row["sql_count"]) for row in logs] == [(500, 1), (200, 1)]
    assert logs[0]["outcome"] == "error"
    assert logs[1]["outcome"] == "ok"


def test_ready_checks_database_and_health_remains_live(client):
    assert client.get("/ready").json() == {"status": "ok"}

    class UnavailableDB:
        def execute(self, statement):
            raise OperationalError("SELECT 1", {}, Exception("private-db-detail"))

    app.dependency_overrides[get_db] = lambda: UnavailableDB()
    try:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        assert client.get("/health").json() == {"status": "ok"}
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_unmatched_urls_and_probes_do_not_log_personal_paths(client, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    client.get("/health")
    client.get("/ready")
    client.get("/not-a-route/private-client-name?secret=private-token")
    logs = records(caplog, "http_request")
    assert len(logs) == 1
    assert logs[0]["route"] == "unmatched"
    assert logs[0]["status"] == 404
    assert "private-client-name" not in json.dumps(logs)
    assert "private-token" not in json.dumps(logs)


def test_import_phases_correlate_with_request(admin_client, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    upload = build_xlsx(
        [
            {
                "Месяц": "2026-01-01",
                "Тип": "HoReCa",
                "Клиент": "private-client",
                "Номенклатура": "private-product",
                "SKU": "RAW",
                "Количество": 1,
                "Вес": 1,
            }
        ]
    )
    response = admin_client.post(
        "/import-xlsx",
        data={"city": "private-city", "csrf_token": CSRF_TOKEN},
        files={"file": ("private-filename.xlsx", upload, XLSX_MIME)},
    )
    assert response.status_code == 200
    phases = records(caplog, "import_phase")
    request = records(caplog, "http_request")[0]
    assert [phase["phase"] for phase in phases] == [
        "read_upload",
        "parse_excel",
        "prepare_columns",
        "prepare_catalog",
        "match_and_build_rows",
        "save_sales",
        "commit_import",
    ]
    assert all(phase["outcome"] == "ok" for phase in phases)
    assert all(phase["request_id"] == request["request_id"] for phase in phases)
    assert request["sql_count"] > 0
    assert "private-" not in json.dumps(phases + [request])


def test_failed_excel_parse_is_measured(admin_client, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    response = admin_client.post(
        "/import-xlsx",
        data={"city": "X", "csrf_token": CSRF_TOKEN},
        files={"file": ("import.xlsx", b"invalid", XLSX_MIME)},
    )
    assert response.status_code == 200
    phases = records(caplog, "import_phase")
    assert [(row["phase"], row["outcome"]) for row in phases] == [
        ("read_upload", "ok"),
        ("parse_excel", "error"),
    ]
