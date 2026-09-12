"""Тонкие обёртки над Telegram Bot API — только то, что нужно диалогу
саморегистрации амбассадора (горизонт 13, Этап 2). Синхронный httpx-клиент,
как и весь остальной проект (везде Depends(get_db), не async ORM).

**Исходящий HTTPS к `api.telegram.org` с прод-VPS заблокирован на уровне
сети** (см. CLAUDE.md, Deploy — подтверждено 2026-09-10: `ping` проходит,
TLS-хендшейк на :443 — нет). Три независимых бота на этом хосте (sarma-crm,
`dziro_bot`, `guide_bot`) упираются в одно и то же — это не код, не конфиг
бота, а сеть целиком. Обход — релей через Cloudflare Worker (запрос
пользователя, 2026-09-12): `TELEGRAM_API_BASE_URL` в `.env` переключает базовый
адрес с `https://api.telegram.org` на URL воркера (`ops/telegram_relay_worker.js`
— тот просто пробрасывает запрос дальше на `api.telegram.org`, у Cloudflare
своя сеть, блокировка её не касается). `TELEGRAM_RELAY_SECRET` — опциональный
общий секрет (заголовок `X-Relay-Secret`), которого требует воркер: без него
URL воркера превращается в открытый прокси к Telegram Bot API для кого угодно,
кто его узнает (сам токен бота — в пути запроса, но воркер не должен
пересылать ЧУЖИЕ токены всем желающим)."""

import os

import httpx

_API_TIMEOUT = 10


def _api_base() -> str:
    return os.getenv("TELEGRAM_API_BASE_URL", "https://api.telegram.org").rstrip("/")


def _relay_headers() -> dict[str, str]:
    secret = os.getenv("TELEGRAM_RELAY_SECRET")
    return {"X-Relay-Secret": secret} if secret else {}


def _api_url(method: str) -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
    return f"{_api_base()}/bot{token}/{method}"


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    httpx.post(
        _api_url("sendMessage"),
        json=payload,
        timeout=_API_TIMEOUT,
        headers=_relay_headers(),
    )


def answer_callback_query(
    callback_query_id: str, text: str | None = None, show_alert: bool = False
) -> None:
    payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
    if text is not None:
        payload["text"] = text
    httpx.post(
        _api_url("answerCallbackQuery"),
        json=payload,
        timeout=_API_TIMEOUT,
        headers=_relay_headers(),
    )


def set_chat_menu_button(chat_id: int, url: str) -> None:
    payload = {
        "chat_id": chat_id,
        "menu_button": {
            "type": "web_app",
            "text": "Открыть",
            "web_app": {"url": url},
        },
    }
    httpx.post(
        _api_url("setChatMenuButton"),
        json=payload,
        timeout=_API_TIMEOUT,
        headers=_relay_headers(),
    )
