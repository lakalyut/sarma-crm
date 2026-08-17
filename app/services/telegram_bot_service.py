"""Горизонт 13, Этап 2 — диалог саморегистрации амбассадора в Telegram-боте.

Состояние диалога не хранится отдельно (без aiogram/FSM — короткий, ровно
двухшаговый диалог не оправдывает отдельную библиотеку/таблицу): читается из
самих nullable-полей User — first_name IS NULL → ждём имя, region_id IS NULL
(при заполненном имени) → ждём регион, оба заполнены → зарегистрирован.
Whitelist — сама таблица users (амбассадор заводится админом заранее на
Этапе 1 с известным telegram_id), отдельной таблицы allowed_users, в отличие
от guide_bot, не нужно — это одна и та же сущность.
"""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import Region
from ..telegram_client import answer_callback_query, send_message, set_chat_menu_button

DENY_TEXT = "🚫 У вас нет доступа к этому боту. Обратитесь к администратору."
ASK_NAME_TEXT = (
    "Добро пожаловать! Отправьте, пожалуйста, имя и фамилию одним сообщением."
)
ASK_REGION_AGAIN_TEXT = "Пожалуйста, выберите регион кнопкой ниже."
ALREADY_REGISTERED_TEXT = (
    "Вы уже зарегистрированы. Открыть мини-апп можно кнопкой меню рядом с полем ввода."
)
REGION_SAVED_TEXT = (
    "Регион сохранён ✅. Открыть мини-апп можно кнопкой меню рядом с полем ввода."
)
REGION_ALREADY_SET_TEXT = "Уже сохранено."


def _ambassador_app_url(base_url: str) -> str:
    return f"{base_url}/ambassador/app"


def _region_keyboard(db: Session) -> dict:
    regions = db.query(Region).order_by(Region.sort_order, Region.id).all()
    return {
        "inline_keyboard": [
            [{"text": r.name, "callback_data": f"region:{r.id}"}] for r in regions
        ]
    }


def _find_ambassador(db: Session, telegram_id: int) -> User | None:
    return (
        db.query(User)
        .filter(User.telegram_id == telegram_id, User.role == "ambassador")
        .first()
    )


def handle_update(db: Session, update: dict, base_url: str) -> None:
    if "message" in update:
        _handle_message(db, update["message"], base_url)
    elif "callback_query" in update:
        _handle_callback_query(db, update["callback_query"], base_url)


def _handle_message(db: Session, message: dict, base_url: str) -> None:
    from_user = message.get("from") or {}
    telegram_id = from_user.get("id")
    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    if telegram_id is None or chat_id is None:
        return

    user = _find_ambassador(db, telegram_id)
    if not user:
        send_message(chat_id, DENY_TEXT)
        return

    if not user.first_name:
        if text == "/start":
            send_message(chat_id, ASK_NAME_TEXT)
            return
        parts = text.split(maxsplit=1)
        if not parts:
            send_message(chat_id, ASK_NAME_TEXT)
            return
        user.first_name = parts[0]
        user.last_name = parts[1] if len(parts) > 1 else ""
        db.commit()
        send_message(chat_id, "Регион:", reply_markup=_region_keyboard(db))
        return

    if not user.region_id:
        send_message(chat_id, ASK_REGION_AGAIN_TEXT, reply_markup=_region_keyboard(db))
        return

    if text == "/start":
        send_message(chat_id, ALREADY_REGISTERED_TEXT)
        set_chat_menu_button(chat_id, _ambassador_app_url(base_url))


def _handle_callback_query(db: Session, callback_query: dict, base_url: str) -> None:
    callback_id = callback_query.get("id")
    from_user = callback_query.get("from") or {}
    telegram_id = from_user.get("id")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    data = callback_query.get("data") or ""

    user = _find_ambassador(db, telegram_id) if telegram_id is not None else None
    if not user:
        answer_callback_query(callback_id, DENY_TEXT, show_alert=True)
        return

    if user.region_id:
        answer_callback_query(callback_id, REGION_ALREADY_SET_TEXT)
        return

    if not data.startswith("region:"):
        answer_callback_query(callback_id)
        return

    try:
        region_id = int(data.split(":", 1)[1])
    except ValueError:
        answer_callback_query(callback_id)
        return

    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        answer_callback_query(callback_id, "Такого региона больше нет, обновите список")
        return

    user.region_id = region.id
    db.commit()
    answer_callback_query(callback_id, "Сохранено ✅")
    if chat_id is not None:
        send_message(chat_id, REGION_SAVED_TEXT)
        set_chat_menu_button(chat_id, _ambassador_app_url(base_url))
