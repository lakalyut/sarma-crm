"""Горизонт 13, Этап 2 — webhook для амбассадорского бота.

Вебхук, не long polling (ROADMAP.md, раздел «Инфраструктура и нагрузка») —
роут внутри уже работающего FastAPI-приложения, без нового контейнера/
процесса. Секрет в заголовке X-Telegram-Bot-Api-Secret-Token — так Telegram
подтверждает, что запрос действительно от него (задаётся при setWebhook)."""

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..database import SessionLocal
from ..services.telegram_bot_service import handle_update

router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    header = request.headers.get("x-telegram-bot-api-secret-token")
    if not secret or header != secret:
        # JSONResponse напрямую, не raise HTTPException — как и в telegram_poc.py,
        # @app.exception_handler(403) в main.py рендерит HTML-страницу ошибки,
        # это же серверный вызов Telegram, не браузерная навигация.
        return JSONResponse(status_code=403, content={"detail": "bad secret"})

    body = await request.json()
    base_url = str(request.base_url).rstrip("/")

    db = SessionLocal()
    try:
        try:
            handle_update(db, body, base_url)
        except Exception as exc:  # noqa: BLE001
            # В проекте нет logging-инфраструктуры (не заводим её здесь отдельной
            # задачей) — но ответ всё равно должен быть 200, иначе Telegram будет
            # бесконечно ретраить один и тот же update.
            print(f"telegram webhook error: {exc!r}")
    finally:
        db.close()

    return {"ok": True}
