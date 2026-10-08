from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import ReleaseUpdate, UpdateDelivery
from ..telegram_client import TelegramSendError, send_update_message

AUDIENCES = {
    "all": "Все пользователи бота",
    "ambassador": "Амбассадоры",
    "user": "Пользователи",
}
STATUSES = {
    "draft": "Черновик",
    "sending": "Отправляется",
    "finished": "Рассылка завершена",
}
DELIVERY_STATUSES = {
    "queued": "В очереди",
    "sending": "Отправляется",
    "sent": "Доставлено",
    "failed": "Ошибка",
    "skipped": "Пропущено",
    "unknown": "Доставка не подтверждена",
}


def validate_text(title: str, body: str, audience: str) -> None:
    if not title.strip() or not body.strip():
        raise ValueError("Заполните заголовок и текст.")
    if (
        len(title.strip()) > 200
        or len(message_text(title.strip(), body.strip())) > 4096
    ):
        raise ValueError(
            "Сообщение слишком длинное: максимум 4096 символов вместе с заголовком."
        )
    if audience not in AUDIENCES:
        raise ValueError("Выберите аудиторию.")


def message_text(title: str, body: str) -> str:
    return f"{title}\n\n{body}"


def import_releases(db: Session, releases: list[dict]) -> int:
    # Validate the entire manifest before writing any drafts.
    for item in releases:
        validate_text(item["title"], item["body"], "all")
        if not isinstance(item["key"], str) or not 1 <= len(item["key"]) <= 120:
            raise ValueError("Invalid release key")
    added = 0
    for item in releases:
        if db.query(ReleaseUpdate.id).filter_by(release_key=item["key"]).first():
            continue
        try:
            with db.begin_nested():
                db.add(
                    ReleaseUpdate(
                        release_key=item["key"],
                        title=item["title"].strip(),
                        body=item["body"].strip(),
                    )
                )
                db.flush()
            added += 1
        except IntegrityError:
            pass  # Concurrent deploy already imported this release.
    db.commit()
    return added


def bot_users(db: Session, audience: str):
    query = db.query(User).filter(
        User.is_active.is_(True),
        User.telegram_id.isnot(None),
        User.role.in_(("ambassador", "user", "brand_ambassador")),
    )
    if audience != "all":
        query = query.filter(User.role == audience)
    return query


def queue_update(db: Session, update_id: int) -> None:
    # Atomic transition prevents double-clicks from creating duplicate deliveries.
    claimed = (
        db.query(ReleaseUpdate)
        .filter_by(id=update_id, status="draft")
        .update({"status": "sending"})
    )
    if not claimed:
        raise ValueError("Это объявление уже отправлено или поставлено в очередь.")
    update = db.get(ReleaseUpdate, update_id)
    validate_text(update.title, update.body, update.audience)
    for user in bot_users(db, update.audience).order_by(User.id).yield_per(100):
        skip = not user.updates_enabled
        db.add(
            UpdateDelivery(
                update_id=update.id,
                telegram_id=user.telegram_id,
                # Existing users have already used the bot before chat tracking existed.
                chat_id=user.telegram_chat_id or user.telegram_id,
                recipient=user.email,
                status="skipped" if skip else "queued",
                error="Уведомления отключены" if skip else None,
            )
        )
    db.flush()
    finish_updates(db)
    db.commit()


def retry_failed(db: Session, update_id: int) -> None:
    update = db.get(ReleaseUpdate, update_id)
    if update.status != "finished":
        raise ValueError("Дождитесь завершения рассылки.")
    changed = (
        db.query(UpdateDelivery)
        .filter_by(update_id=update_id, status="failed")
        .update({"status": "queued", "error": None})
    )
    if not changed:
        raise ValueError("Нет ошибок для повторной отправки.")
    update.status = "sending"
    db.commit()


def finish_updates(db: Session) -> None:
    pending = db.query(UpdateDelivery.update_id).filter(
        UpdateDelivery.status.in_(("queued", "sending"))
    )
    db.query(ReleaseUpdate).filter(
        ReleaseUpdate.status == "sending", ~ReleaseUpdate.id.in_(pending)
    ).update(
        {"status": "finished", "sent_at": datetime.now(UTC)}, synchronize_session=False
    )


def delivery_counts(db: Session, update_id: int) -> dict:
    return dict(
        db.query(UpdateDelivery.status, func.count(UpdateDelivery.id))
        .filter_by(update_id=update_id)
        .group_by(UpdateDelivery.status)
        .all()
    )


def recover_interrupted(db: Session) -> None:
    # Telegram offers no idempotency key: a crash after send may mean delivered.
    # Do not automatically resend unacknowledged messages and risk duplicates.
    db.query(UpdateDelivery).filter_by(status="sending").update(
        {
            "status": "unknown",
            "error": "Отправка прервана; повтор исключён во избежание дубля.",
        }
    )
    finish_updates(db)
    db.commit()


def deliver_next(db: Session) -> float:
    delivery = (
        db.query(UpdateDelivery)
        .filter_by(status="queued")
        .order_by(UpdateDelivery.id)
        .first()
    )
    if not delivery:
        finish_updates(db)
        db.commit()
        return 2
    claimed = (
        db.query(UpdateDelivery)
        .filter_by(id=delivery.id, status="queued")
        .update({"status": "sending", "attempted_at": datetime.now(UTC), "error": None})
    )
    db.commit()
    if not claimed:
        return 0.1
    user = db.query(User).filter_by(telegram_id=delivery.telegram_id).first()
    update = db.get(ReleaseUpdate, delivery.update_id)
    if (
        not user
        or not user.is_active
        or not user.updates_enabled
        or user.role not in ("user", "ambassador", "brand_ambassador")
        or (update.audience != "all" and user.role != update.audience)
        or (user.telegram_chat_id or user.telegram_id) != delivery.chat_id
    ):
        delivery.status = "skipped"
        delivery.error = "Получатель недоступен или отключил уведомления"
    else:
        try:
            send_update_message(
                delivery.chat_id, message_text(update.title, update.body)
            )
        except TelegramSendError as exc:
            delivery.status = "failed"
            delivery.error = (
                "Бот заблокирован или нет доступа"
                if exc.code == 403
                else f"Telegram: ошибка {exc.code}"
            )
            if exc.code == 429:
                delivery.status = "queued"
                db.commit()
                return max(1, min(exc.retry_after, 3600))
        except (
            Exception
        ):  # noqa: BLE001 — network may fail after Telegram accepted the message.
            delivery.status = "unknown"
            delivery.error = (
                "Нет подтверждения от Telegram; повтор исключён во избежание дубля."
            )
        else:
            delivery.status = "sent"
            delivery.delivered_at = datetime.now(UTC)
    db.flush()
    finish_updates(db)
    db.commit()
    return 0.1  # At most 10 messages per second.
