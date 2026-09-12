"""telegram_poller.py — long polling вместо вебхука (симметричная сетевая
блокировка: Telegram тоже не может достучаться до нас — подтверждено
getWebhookInfo/last_error_message="Connection timed out", 2026-09-12).

Фоновый поток тут не тестируется напрямую (реальная сеть/бесконечный цикл) —
проверяем по отдельности: (1) охранные условия start() не запускают лишнего;
(2) чистую логику одного шага поллинга/обработки апдейта, без сети и БД."""


def test_start_noop_without_polling_enabled(monkeypatch):
    from app import telegram_poller

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_POLLING_ENABLED", raising=False)
    telegram_poller._thread = None

    telegram_poller.start()

    assert telegram_poller._thread is None


def test_start_noop_without_token(monkeypatch):
    from app import telegram_poller

    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "1")
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    telegram_poller._thread = None

    telegram_poller.start()

    assert telegram_poller._thread is None


def test_start_spawns_thread_when_enabled(monkeypatch):
    from app import telegram_poller

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "1")
    # подменяем сам цикл — не лезем в реальную сеть в тесте
    monkeypatch.setattr(telegram_poller, "_poll_loop", lambda: None)
    telegram_poller._thread = None

    telegram_poller.start()

    assert telegram_poller._thread is not None
    telegram_poller._thread.join(timeout=2)
    telegram_poller.stop()
    telegram_poller._thread = None


def test_start_is_idempotent(monkeypatch):
    from app import telegram_poller

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_POLLING_ENABLED", "1")
    calls = []
    monkeypatch.setattr(
        telegram_poller,
        "_poll_loop",
        lambda: calls.append(1) or None,
    )
    telegram_poller._thread = None

    telegram_poller.start()
    first_thread = telegram_poller._thread
    telegram_poller.start()  # повторный вызов — не должен создать второй поток

    assert telegram_poller._thread is first_thread
    first_thread.join(timeout=2)
    telegram_poller.stop()
    telegram_poller._thread = None


def test_poll_once_advances_offset_to_last_update_plus_one(monkeypatch):
    from app import telegram_poller

    monkeypatch.setattr(
        telegram_poller,
        "get_updates",
        lambda offset, timeout: [{"update_id": 5}, {"update_id": 7}],
    )

    updates, new_offset = telegram_poller._poll_once(None, "https://x")

    assert len(updates) == 2
    assert new_offset == 8


def test_poll_once_keeps_offset_when_no_updates(monkeypatch):
    from app import telegram_poller

    monkeypatch.setattr(telegram_poller, "get_updates", lambda offset, timeout: [])

    updates, new_offset = telegram_poller._poll_once(3, "https://x")

    assert updates == []
    assert new_offset == 3


def test_process_update_calls_handle_update(monkeypatch):
    from app import telegram_poller

    calls = []
    monkeypatch.setattr(
        telegram_poller,
        "handle_update",
        lambda db, update, base_url: calls.append((db, update, base_url)),
    )

    telegram_poller._process_update("db", {"update_id": 1}, "https://x")

    assert calls == [("db", {"update_id": 1}, "https://x")]


def test_process_update_swallows_handler_errors(monkeypatch):
    from app import telegram_poller

    def boom(db, update, base_url):
        raise RuntimeError("boom")

    monkeypatch.setattr(telegram_poller, "handle_update", boom)

    # не должно поднять исключение наружу
    telegram_poller._process_update("db", {"update_id": 1}, "https://x")


def test_public_base_url_default(monkeypatch):
    from app import telegram_poller

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert telegram_poller._public_base_url() == "https://sarma-crm.ru"


def test_public_base_url_override(monkeypatch):
    from app import telegram_poller

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://staging.example.com/")
    assert telegram_poller._public_base_url() == "https://staging.example.com"
