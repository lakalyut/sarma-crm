"""Проверка подписи Telegram WebApp initData — общая для всех мини-апп
эндпоинтов (PoC горизонта 13/Этапа 0 и мини-апп амбассадора Этапа 2).

Как это работает: Telegram подписывает initData секретом, производным от
токена бота; пересчитываем подпись на бэкенде и сравниваем с присланной.
Документация: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

Логика перенесена сюда из app/routes/telegram_poc.py дословно (была
скопирована из guide_bot/webapp/auth.py) — теперь используется не только PoC.
"""

import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .auth_models import User
from .database import get_db

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


def get_current_ambassador(
    authorization: str = Header(default=""),
    db: Session = Depends(get_db),
) -> User:
    """Аутентификация мини-аппа амбассадора — заголовок Authorization: tma
    <initData>, не cookie-сессия (initData сама по себе уже подписана
    секретом бота, ambient-cookie тут не участвует). Требует, чтобы
    telegram_id был известен (создан админом на Этапе 1) и чтобы
    саморегистрация в боте (Этап 2) уже сохранила имя и регион."""
    if not authorization.startswith("tma "):
        raise HTTPException(
            status_code=401, detail="Нет заголовка Authorization: tma <initData>"
        )

    raw_init_data = authorization[len("tma ") :]

    try:
        parsed = verify_init_data(raw_init_data)
    except InitDataError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    tg_user = parsed.get("user") or {}
    telegram_id = tg_user.get("id")
    if telegram_id is None:
        raise HTTPException(status_code=401, detail="В initData нет пользователя")

    user = (
        db.query(User)
        .filter(User.telegram_id == telegram_id, User.role == "ambassador")
        .first()
    )
    if not user:
        raise HTTPException(status_code=403, detail="Амбассадор не найден")

    if not user.first_name or not user.region_id:
        raise HTTPException(
            status_code=403, detail="Регистрация в боте ещё не завершена"
        )

    return user
