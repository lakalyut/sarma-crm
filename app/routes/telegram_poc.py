"""Горизонт 13, Этап 0 — мини-PoC Telegram WebApp initData-авторизации.

Проверяет сам механизм (подпись initData + реальный Telegram WebView, включая
iOS) до того, как строить что-либо поверх. Тестовый бот, не прод. Логика
verify_init_data() — адаптация app/webapp/auth.py из guide_bot (тот же
подтверждённый на проде паттерн), см. ROADMAP.md, горизонт 13.
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..templating import templates

router = APIRouter()

MAX_AUTH_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    """initData отсутствует, повреждена или подпись не совпала."""


def _bot_token() -> str:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
    return token


def verify_init_data(
    init_data: str, max_age_seconds: int = MAX_AUTH_AGE_SECONDS
) -> dict:
    """Проверяет подпись initData, возвращает распарсенные поля
    (включая "user" как dict). Бросает InitDataError, если что-то не так."""
    if not init_data:
        raise InitDataError("initData отсутствует")

    pairs = parse_qsl(init_data, strict_parsing=True, keep_blank_values=True)
    data = dict(pairs)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise InitDataError("В initData нет hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))

    secret_key = hmac.new(b"WebAppData", _bot_token().encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        raise InitDataError("Подпись initData не совпадает")

    auth_date = data.get("auth_date")
    if auth_date is not None:
        age = time.time() - int(auth_date)
        if age > max_age_seconds:
            raise InitDataError("initData устарела, перезапустите мини-апп")

    if "user" in data:
        try:
            data["user"] = json.loads(data["user"])
        except (json.JSONDecodeError, TypeError) as exc:
            raise InitDataError("Не удалось распарсить поле user") from exc

    return data


@router.get("/poc/telegram", response_class=HTMLResponse)
def telegram_poc_page(request: Request):
    return templates.TemplateResponse("poc/telegram.html", {"request": request})


@router.post("/poc/telegram/verify")
async def telegram_poc_verify(request: Request):
    # JSONResponse напрямую, не raise HTTPException — @app.exception_handler(401)
    # в main.py безусловно редиректит на /auth/login (это API-эндпоинт мини-аппа,
    # не браузерная навигация), а 403/404/500 там же рендерят HTML-страницы
    # ошибок. Raise здесь тихо превратил бы JSON-ответ в редирект/HTML для
    # fetch() на фронте.
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("tma "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Нет заголовка Authorization: tma <initData>"},
        )

    raw_init_data = authorization[len("tma ") :]

    try:
        parsed = verify_init_data(raw_init_data)
    except InitDataError as exc:
        return JSONResponse(status_code=401, content={"detail": str(exc)})

    user = parsed.get("user") or {}

    return {
        "ok": True,
        "telegram_id": user.get("id"),
        "first_name": user.get("first_name"),
        "last_name": user.get("last_name"),
        "username": user.get("username"),
        "auth_date": parsed.get("auth_date"),
    }
