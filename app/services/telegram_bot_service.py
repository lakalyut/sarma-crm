"""Горизонт 13, Этап 2 — диалог саморегистрации амбассадора в Telegram-боте.

Состояние диалога не хранится отдельно (без aiogram/FSM — короткий, ровно
двухшаговый диалог не оправдывает отдельную библиотеку/таблицу): читается из
самих nullable-полей User — first_name IS NULL → ждём имя, city IS NULL
(при заполненном имени) → ждём город, оба заполнены → зарегистрирован.
Whitelist — сама таблица users (амбассадор заводится админом заранее на
Этапе 1 с известным telegram_id), отдельной таблицы allowed_users, в отличие
от guide_bot, не нужно — это одна и та же сущность.

Амбассадор привязан к одному конкретному городу (User.city — та же природа
поле, что Sale.city/Visit.city), не к макро-региону — выбор всё ещё через
инлайн-кнопки, не свободный текст (та же причина, что была у региона: город
— граница доступа к списку клиентов, опечатка не должна давать несуществующий
город)."""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..services.sales_options_service import get_cities
from ..telegram_client import answer_callback_query, send_message, set_chat_menu_button

DENY_TEXT = "🚫 У вас нет доступа к этому боту. Обратитесь к администратору."
ASK_NAME_TEXT = (
    "Добро пожаловать! Отправьте, пожалуйста, имя и фамилию одним сообщением."
)
ASK_CITY_AGAIN_TEXT = "Пожалуйста, выберите город кнопкой ниже."
ALREADY_REGISTERED_TEXT = (
    "Вы уже зарегистрированы. Открыть мини-апп можно кнопкой меню рядом с полем ввода."
)
CITY_SAVED_TEXT = (
    "Город сохранён ✅. Открыть мини-апп можно кнопкой меню рядом с полем ввода."
)
CITY_ALREADY_SET_TEXT = "Уже сохранено."


def _ambassador_app_url(base_url: str) -> str:
    return f"{base_url}/ambassador/app"


def _city_keyboard(db: Session) -> dict:
    cities = get_cities(db)
    return {
        "inline_keyboard": [[{"text": c, "callback_data": f"city:{c}"}] for c in cities]
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
        send_message(chat_id, "Город:", reply_markup=_city_keyboard(db))
        return

    if not user.city:
        send_message(chat_id, ASK_CITY_AGAIN_TEXT, reply_markup=_city_keyboard(db))
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

    if user.city:
        answer_callback_query(callback_id, CITY_ALREADY_SET_TEXT)
        return

    if not data.startswith("city:"):
        answer_callback_query(callback_id)
        return

    city = data.split(":", 1)[1]
    if city not in get_cities(db):
        answer_callback_query(callback_id, "Такого города больше нет, обновите список")
        return

    user.city = city
    db.commit()
    answer_callback_query(callback_id, "Сохранено ✅")
    if chat_id is not None:
        send_message(chat_id, CITY_SAVED_TEXT)
        set_chat_menu_button(chat_id, _ambassador_app_url(base_url))
