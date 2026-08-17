"""Тонкие обёртки над Telegram Bot API — только то, что нужно диалогу
саморегистрации амбассадора (горизонт 13, Этап 2). Синхронный httpx-клиент,
как и весь остальной проект (везде Depends(get_db), не async ORM)."""

import os

import httpx

_API_TIMEOUT = 10


def _api_url(method: str) -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
    return f"https://api.telegram.org/bot{token}/{method}"


def send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    httpx.post(_api_url("sendMessage"), json=payload, timeout=_API_TIMEOUT)


def answer_callback_query(
    callback_query_id: str, text: str | None = None, show_alert: bool = False
) -> None:
    payload = {"callback_query_id": callback_query_id, "show_alert": show_alert}
    if text is not None:
        payload["text"] = text
    httpx.post(_api_url("answerCallbackQuery"), json=payload, timeout=_API_TIMEOUT)


def set_chat_menu_button(chat_id: int, url: str) -> None:
    payload = {
        "chat_id": chat_id,
        "menu_button": {
            "type": "web_app",
            "text": "Открыть",
            "web_app": {"url": url},
        },
    }
    httpx.post(_api_url("setChatMenuButton"), json=payload, timeout=_API_TIMEOUT)
