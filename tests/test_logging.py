import json
import logging
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import telegram_poller
from app.logging_config import JsonFormatter, configure_logging
from app.observability import RequestMetricsMiddleware, set_actor
from tests.conftest import CSRF_TOKEN
from tests.test_observability import records


def test_login_result_and_actor_are_correlated_without_credentials(
    client, admin_user, caplog
):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    data = {
        "email": admin_user.email,
        "password": "wrong-private-password",
        "csrf_token": CSRF_TOKEN,
    }
    client.post("/auth/login", data=data)
    data["password"] = "test-password-123"
    response = client.post("/auth/login", data=data, follow_redirects=False)
    actions = records(caplog, "user_action")
    assert [(row["action"], row["outcome"]) for row in actions] == [
        ("login", "rejected"),
        ("login", "success"),
    ]
    assert actions[0]["user_id"] is None
    assert actions[1]["user_id"] == admin_user.id
    assert actions[1]["request_id"] == response.headers["x-request-id"]
    requests = records(caplog, "http_request")
    assert requests[-1]["user_id"] == admin_user.id
    messages = json.dumps(actions + requests)
    assert admin_user.email not in messages
    assert "private-password" not in messages
    assert "test-password-123" not in messages


def test_rejected_user_change_is_not_logged_as_success(
    admin_client, admin_user, caplog
):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    response = admin_client.post(
        f"/admin/users/{admin_user.id}/delete", data={"csrf_token": CSRF_TOKEN}
    )
    assert response.status_code == 200
    assert records(caplog, "user_action") == []
    assert records(caplog, "http_request")[0]["user_id"] == admin_user.id


def test_user_creation_is_logged_after_commit_only(
    admin_client, db_session, monkeypatch, caplog
):
    from sqlalchemy.orm import Session

    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    response = admin_client.post(
        "/admin/users/new",
        data={"email": "new@test.local", "role": "user", "csrf_token": CSRF_TOKEN},
    )
    assert response.status_code == 200
    assert [row["action"] for row in records(caplog, "user_action")] == [
        "user_created",
        "password_reset_link_created",
    ]
    caplog.clear()

    def fail_commit(self):
        raise RuntimeError("private-db-value")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError):
        admin_client.post(
            "/admin/users/new",
            data={
                "email": "failed@test.local",
                "role": "user",
                "csrf_token": CSRF_TOKEN,
            },
        )
    assert records(caplog, "user_action") == []


def test_slow_request_and_error_levels_and_context_cleanup(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")
    monkeypatch.setenv("SLOW_REQUEST_MS", "0.000001")
    app = FastAPI()
    app.add_middleware(RequestMetricsMiddleware)

    @app.get("/fail")
    def fail():
        set_actor(42, "admin")
        raise RuntimeError("private-error-secret")

    @app.get("/ok")
    def ok():
        return {"ok": True}

    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/fail")
        response = client.get("/ok", headers={"X-Request-ID": "untrusted-id"})
    error = records(caplog, "request_error")[0]
    requests = records(caplog, "http_request")
    assert error["user_id"] == requests[0]["user_id"] == 42
    assert error["request_id"] == requests[0]["request_id"]
    assert error["error_type"] == "RuntimeError"
    assert error["traceback"][-1]["function"] == "fail"
    assert requests[1]["user_id"] is None
    assert requests[1]["slow"] is True
    assert (
        response.headers["x-request-id"] == requests[1]["request_id"] != "untrusted-id"
    )
    logged = [row for row in caplog.records if row.name == "uvicorn.error.pulse"]
    assert [row.levelname for row in logged] == ["ERROR", "ERROR", "WARNING"]
    assert "private-error-secret" not in "".join(row.getMessage() for row in logged)


def test_telegram_errors_do_not_expose_token_urls(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error.pulse")

    def fail(*args):
        raise RuntimeError("https://api.telegram.org/botprivate-token/getUpdates")

    monkeypatch.setattr(telegram_poller, "handle_update", fail)
    telegram_poller._process_update(None, {}, "https://example.com")
    record = records(caplog, "telegram_update_error")[0]
    assert record["error_type"] == "RuntimeError"
    assert record["traceback"][-1]["function"] == "fail"
    assert "private-token" not in caplog.text


def test_formatter_preserves_metrics_and_sanitizes_server_tracebacks():
    from app.performance_report import summarize

    metric = {
        "event": "http_request",
        "method": "GET",
        "route": "/",
        "status": 200,
        "duration_ms": 12,
        "sql_count": 1,
        "sql_duration_ms": 2,
    }
    record = logging.LogRecord(
        "uvicorn.error.pulse", logging.INFO, __file__, 1, json.dumps(metric), (), None
    )
    line = JsonFormatter().format(record)
    assert json.loads(line)["level"] == "INFO"
    assert json.loads(line)["timestamp"].endswith("+00:00")
    assert summarize([line])["requests"][0]["requests"] == 1
    try:
        raise RuntimeError("private-exception-message")
    except RuntimeError:
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application",
            (),
            sys.exc_info(),
        )
    line = JsonFormatter().format(record)
    assert json.loads(line)["error_type"] == "RuntimeError"
    assert "private-exception-message" not in line


def test_logging_configuration_is_idempotent():
    configure_logging()
    configure_logging()
    handlers = logging.getLogger().handlers
    assert (
        sum(isinstance(handler.formatter, JsonFormatter) for handler in handlers) == 1
    )
    assert logging.getLogger("uvicorn.access").disabled is True
