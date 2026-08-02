from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import EventLog


def log_import(
    db: Session,
    city: str,
    months: list[str],
    rows_imported: int,
    rows_unmatched: int,
    user_id: int | None,
) -> None:
    db.add(
        EventLog(
            event_type="import",
            city=city,
            months=", ".join(sorted(m for m in months if m)),
            rows_imported=rows_imported,
            rows_unmatched=rows_unmatched,
            user_id=user_id,
        )
    )
    db.commit()


def list_events(db: Session, city: str | None = None) -> list[EventLog]:
    q = db.query(EventLog).order_by(EventLog.created_at.desc())
    if city:
        q = q.filter(EventLog.city == city)
    return q.all()


def count_unread_events(db: Session, user: User | None) -> int:
    if not user:
        return 0

    q = db.query(func.count(EventLog.id))
    if user.events_last_seen_at is not None:
        q = q.filter(EventLog.created_at > user.events_last_seen_at)
    return int(q.scalar() or 0)


def mark_events_seen(db: Session, user: User) -> None:
    user.events_last_seen_at = datetime.now(UTC)
    db.commit()


def relative_day_label(created_at: datetime) -> str:
    today = datetime.now(UTC).date()
    day = created_at.date()

    if day == today:
        return "сегодня"
    if day == today - timedelta(days=1):
        return "вчера"
    return created_at.strftime("%d.%m.%Y")
