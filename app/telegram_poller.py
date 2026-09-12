"""Long polling для амбассадорского Telegram-бота — обход симметричной
сетевой блокировки (см. `telegram_client.py`): серверы Telegram не могут
достучаться до нас так же, как мы не могли достучаться до них, поэтому
`POST /telegram/webhook` (app/routes/telegram_bot.py) больше не работает в
проде. Вместо push (Telegram -> мы) — pull (мы -> Telegram через тот же
Cloudflare Worker-релей, что и исходящие `sendMessage`): бот сам регулярно
спрашивает `getUpdates`.

Переиспользует тот же `handle_update()`, что раньше вызывался из вебхук-роута
— бизнес-логика (services/telegram_bot_service.py) ничего не знает, откуда
пришёл апдейт, вебхук-роут остаётся в коде нетронутым на случай, если
блокировку когда-нибудь снимут и можно будет вернуться к push.

Фоновый поток, не отдельный контейнер/процесс — прод гоняет ровно один
uvicorn-воркер без `--reload` (см. Dockerfile), значит поток запустится
единожды, не продублируется. Включается явно через `TELEGRAM_POLLING_ENABLED`
(тот же принцип, что `AUTO_CREATE_SCHEMA` в main.py) — не просто по наличию
`TELEGRAM_TOKEN`: тесты держат фиктивный токен в окружении постоянно
(tests/conftest.py), без отдельного флага автоматически заводили бы поток,
дёргающий сеть, на каждый прогон pytest."""

import os
import threading

from .database import SessionLocal
from .services.telegram_bot_service import handle_update
from .telegram_client import delete_webhook, get_updates

_POLL_TIMEOUT = 25  # секунд long-poll внутри одного вызова getUpdates
_ERROR_BACKOFF = 5  # секунд паузы после сетевой ошибки, не долбить впустую

_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://sarma-crm.ru").rstrip("/")


def _process_update(db, update: dict, base_url: str) -> None:
    try:
        handle_update(db, update, base_url)
    except Exception as exc:  # noqa: BLE001 — тот же принцип, что был в вебхуке:
        # один сломанный апдейт не должен уронить весь цикл поллинга.
        print(f"telegram poller: handle_update error: {exc!r}")


def _poll_once(offset: int | None, base_url: str) -> tuple[list[dict], int | None]:
    """Один вызов getUpdates + новый offset (id последнего апдейта + 1).
    Отдельно от обработки в БД — так это тестируется без реальной БД/сети."""
    updates = get_updates(offset=offset, timeout=_POLL_TIMEOUT)
    new_offset = offset
    for update in updates:
        new_offset = update["update_id"] + 1
    return updates, new_offset


def _poll_loop() -> None:
    try:
        delete_webhook()
    except Exception as exc:  # noqa: BLE001
        print(f"telegram poller: deleteWebhook error: {exc!r}")

    offset: int | None = None
    base_url = _public_base_url()

    while not _stop_event.is_set():
        try:
            updates, offset = _poll_once(offset, base_url)
        except Exception as exc:  # noqa: BLE001 — сеть моргнула — не падаем,
            # пробуем ещё раз после паузы.
            print(f"telegram poller: getUpdates error: {exc!r}")
            _stop_event.wait(_ERROR_BACKOFF)
            continue

        for update in updates:
            db = SessionLocal()
            try:
                _process_update(db, update, base_url)
            finally:
                db.close()


def start() -> None:
    """Звать один раз при старте приложения (main.py::lifespan). Ничего не
    делает без TELEGRAM_TOKEN (бот просто не настроен — не ошибка) или без
    явного TELEGRAM_POLLING_ENABLED=1."""
    global _thread
    if os.getenv("TELEGRAM_POLLING_ENABLED") != "1":
        return
    if not os.getenv("TELEGRAM_TOKEN"):
        return
    if _thread is not None:
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_poll_loop, name="telegram-poller", daemon=True)
    _thread.start()


def stop() -> None:
    _stop_event.set()
