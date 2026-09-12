"""telegram_client.py — базовый URL Bot API переключаемый через
TELEGRAM_API_BASE_URL (обход блокировки api.telegram.org с прод-VPS релеем
через Cloudflare Worker, запрос пользователя 2026-09-12) + опциональный
заголовок-секрет TELEGRAM_RELAY_SECRET."""


def test_api_url_defaults_to_telegram_org(monkeypatch):
    from app import telegram_client

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.delenv("TELEGRAM_API_BASE_URL", raising=False)

    assert (
        telegram_client._api_url("sendMessage")
        == "https://api.telegram.org/bot123:abc/sendMessage"
    )


def test_api_url_uses_relay_base_when_set(monkeypatch):
    from app import telegram_client

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_API_BASE_URL", "https://my-relay.example.workers.dev/")

    assert (
        telegram_client._api_url("sendMessage")
        == "https://my-relay.example.workers.dev/bot123:abc/sendMessage"
    )


def test_relay_headers_empty_without_secret(monkeypatch):
    from app import telegram_client

    monkeypatch.delenv("TELEGRAM_RELAY_SECRET", raising=False)
    assert telegram_client._relay_headers() == {}


def test_relay_headers_include_secret_when_set(monkeypatch):
    from app import telegram_client

    monkeypatch.setenv("TELEGRAM_RELAY_SECRET", "s3cr3t")
    assert telegram_client._relay_headers() == {"X-Relay-Secret": "s3cr3t"}


def test_send_message_passes_relay_headers(monkeypatch):
    from app import telegram_client

    monkeypatch.setenv("TELEGRAM_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_RELAY_SECRET", "s3cr3t")

    calls = []
    monkeypatch.setattr(
        telegram_client.httpx,
        "post",
        lambda url, json, timeout, headers: calls.append(
            {"url": url, "json": json, "headers": headers}
        ),
    )

    telegram_client.send_message(42, "привет")

    assert len(calls) == 1
    assert calls[0]["headers"] == {"X-Relay-Secret": "s3cr3t"}
    assert calls[0]["json"]["chat_id"] == 42
