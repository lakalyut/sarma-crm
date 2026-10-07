"""Persistent queue, one sender thread in the existing single-worker deployment."""

import logging
import os
import threading

from .database import SessionLocal
from .services.release_update_service import deliver_next, recover_interrupted

_stop = threading.Event()
_thread = None
logger = logging.getLogger(__name__)


def _run():
    recover = True
    while not _stop.is_set():
        delay = 5
        try:
            with SessionLocal() as db:
                if recover:
                    recover_interrupted(db)
                    recover = False
                delay = deliver_next(db)
        except Exception:  # noqa: BLE001
            logger.error("Update sender database error; will retry")
            recover = True
        _stop.wait(delay)


def start():
    global _thread
    if not os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_POLLING_ENABLED") != "1":
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name="update-sender", daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=12)
