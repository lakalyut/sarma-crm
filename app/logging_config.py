"""JSON console logs collected and rotated by Docker."""

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime


def exception_details(exc):
    # Exception messages can contain SQL values, passwords or Telegram token URLs.
    return {
        "error_type": type(exc).__name__,
        "traceback": [
            {
                "module": frame.f_globals.get("__name__", ""),
                "function": frame.f_code.co_name,
                "line": line,
            }
            for frame, line in traceback.walk_tb(exc.__traceback__)
        ],
    }


class JsonFormatter(logging.Formatter):
    def format(self, record):
        if record.name == "uvicorn.error.pulse":
            fields = json.loads(record.getMessage())
        else:
            fields = {"event": "server_log", "message": record.getMessage()}
        fields.update(
            timestamp=datetime.fromtimestamp(record.created, UTC).isoformat(),
            level=record.levelname,
            logger=record.name,
        )
        if record.exc_info and record.exc_info[1]:
            fields.update(exception_details(record.exc_info[1]))
        return json.dumps(fields, ensure_ascii=False)


def configure_logging():
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    if level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR or CRITICAL")

    root = logging.getLogger()
    if not any(
        isinstance(handler.formatter, JsonFormatter) for handler in root.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    logging.getLogger("uvicorn.error.pulse").setLevel(level)
    # The middleware records route templates instead of raw URLs and query strings.
    logging.getLogger("uvicorn.access").disabled = True
