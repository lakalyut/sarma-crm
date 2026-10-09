"""Request and import timings without SQL text, parameters or personal data."""

import json
import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from sqlalchemy import event

logger = logging.getLogger("uvicorn.error.pulse")


@dataclass
class RequestMetrics:
    request_id: str
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


def _log(event_name, **fields):
    logger.info(json.dumps({"event": event_name, **fields}, ensure_ascii=False))


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
            request_id=metrics.request_id if metrics else None,
            phase=phase,
            outcome=outcome,
            duration_ms=round((perf_counter() - started) * 1000, 2),
        )


class RequestMetricsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        metrics = RequestMetrics(request_id=uuid4().hex)
        token = _current_metrics.set(metrics)
        started = perf_counter()
        status = 500
        response_bytes = 0
        outcome = "error"

        async def measured_send(message):
            nonlocal status, response_bytes
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                response_bytes += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
            outcome = "ok"
        finally:
            _current_metrics.reset(token)
            route = scope.get("route")
            # Route templates exclude customer names, IDs and arbitrary URLs.
            route_name = getattr(route, "path", "unmatched")
            if (route_name not in ("/health", "/ready") or status >= 500) and scope.get(
                "path", ""
            ).split("/")[1:2] != ["static"]:
                _log(
                    "http_request",
                    request_id=metrics.request_id,
                    method=scope["method"],
                    route=route_name,
                    status=status,
                    outcome=outcome,
                    duration_ms=round((perf_counter() - started) * 1000, 2),
                    sql_count=metrics.sql_count,
                    sql_duration_ms=round(metrics.sql_seconds * 1000, 2),
                    response_bytes=response_bytes,
                )
