"""Request timings and action logs with internal user IDs and no payloads."""

import json
import logging
import math
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from sqlalchemy import event

from .logging_config import exception_details

logger = logging.getLogger("uvicorn.error.pulse")


@dataclass
class RequestMetrics:
    request_id: str
    user_id: int | None = None
    user_role: str | None = None
    sql_count: int = 0
    sql_seconds: float = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_sql(self, seconds):
        # Sync dependencies/routes share this object through copied contexts.
        with self.lock:
            self.sql_count += 1
            self.sql_seconds += seconds


_current_metrics: ContextVar[RequestMetrics | None] = ContextVar(
    "pulse_request_metrics", default=None
)


def install_sql_metrics(engine):
    if event.contains(engine, "before_cursor_execute", _sql_start):
        return
    event.listen(engine, "before_cursor_execute", _sql_start)
    event.listen(engine, "after_cursor_execute", _sql_finish)
    event.listen(engine, "handle_error", _sql_error)


def _sql_start(conn, cursor, statement, parameters, context, executemany):
    metrics = _current_metrics.get()
    if metrics is not None:
        context._pulse_timing = (metrics, perf_counter())


def _record_execution(context):
    timing = getattr(context, "_pulse_timing", None)
    if timing is not None:
        del context._pulse_timing
        metrics, started = timing
        metrics.record_sql(perf_counter() - started)


def _sql_finish(conn, cursor, statement, parameters, context, executemany):
    _record_execution(context)


def _sql_error(exception_context):
    _record_execution(exception_context.execution_context)


def set_actor(user_id, role):
    metrics = _current_metrics.get()
    if metrics is not None:
        metrics.user_id = user_id
        metrics.user_role = role


def _log(event_name, *, level=logging.INFO, **fields):
    metrics = _current_metrics.get()
    context = {
        "request_id": metrics.request_id if metrics else None,
        "user_id": metrics.user_id if metrics else None,
        "user_role": metrics.user_role if metrics else None,
    }
    logger.log(
        level,
        json.dumps({"event": event_name, **context, **fields}, ensure_ascii=False),
    )


def log_exception(event_name, exc, **fields):
    _log(event_name, level=logging.ERROR, **exception_details(exc), **fields)


def log_action(action, *, outcome="success", **fields):
    level = logging.INFO if outcome == "success" else logging.WARNING
    _log("user_action", level=level, action=action, outcome=outcome, **fields)


@contextmanager
def import_phase(phase):
    started = perf_counter()
    outcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        metrics = _current_metrics.get()
        _log(
            "import_phase",
            level=logging.INFO if outcome == "ok" else logging.ERROR,
            request_id=metrics.request_id if metrics else None,
            phase=phase,
            outcome=outcome,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )


class RequestMetricsMiddleware:
    def __init__(self, app):
        self.app = app
        self.slow_request_ms = float(os.getenv("SLOW_REQUEST_MS", "2000"))
        if not math.isfinite(self.slow_request_ms) or self.slow_request_ms <= 0:
            raise ValueError("SLOW_REQUEST_MS must be a positive finite number")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        metrics = RequestMetrics(request_id=uuid4().hex)
        scope["pulse_request_id"] = metrics.request_id
        token = _current_metrics.set(metrics)
        started = perf_counter()
        status = 500
        response_bytes = 0
        outcome = "error"

        async def measured_send(message):
            nonlocal status, response_bytes
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": headers
                    + [(b"x-request-id", metrics.request_id.encode())],
                }
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
            outcome = "error" if status >= 400 else "ok"
        except Exception as exc:
            log_exception("request_error", exc)
            raise
        finally:
            route = scope.get("route")
            # Route templates exclude customer names, IDs and arbitrary URLs.
            route_name = getattr(route, "path", "unmatched")
            duration_ms = round((perf_counter() - started) * 1000, 2)
            slow = duration_ms >= self.slow_request_ms
            level = logging.INFO
            if status >= 400 or slow:
                level = logging.WARNING
            if status >= 500 or outcome == "error" and status < 400:
                level = logging.ERROR
            quiet = route_name in ("/health", "/ready") or scope.get(
                "path", ""
            ).startswith("/static/")
            try:
                if not quiet or status >= 400 or slow:
                    _log(
                        "http_request",
                        level=level,
                        method=scope["method"],
                        route=route_name,
                        status=status,
                        outcome=outcome,
                        slow=slow,
                        duration_ms=duration_ms,
                        sql_count=metrics.sql_count,
                        sql_duration_ms=round(metrics.sql_seconds * 1000, 2),
                        response_bytes=response_bytes,
                    )
            finally:
                _current_metrics.reset(token)
