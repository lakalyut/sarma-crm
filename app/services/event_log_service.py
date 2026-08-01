from sqlalchemy.orm import Session

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
