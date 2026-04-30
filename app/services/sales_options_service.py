from sqlalchemy.orm import Session

from ..models import Sale
from ..utils.dates import month_sort_key


def get_cities(db: Session) -> list[str]:
    return [
        row[0] for row in db.query(Sale.city).distinct().order_by(Sale.city) if row[0]
    ]


def get_months(db: Session, city: str | None = None, reverse: bool = True) -> list[str]:
    query = db.query(Sale.month).filter(Sale.month.isnot(None))

    if city:
        query = query.filter(Sale.city == city)

    months = [row[0] for row in query.distinct().all() if row[0]]

    return sorted(months, key=month_sort_key, reverse=reverse)


def get_types(db: Session, city: str | None = None) -> list[str]:
    query = db.query(Sale.type).filter(Sale.type.isnot(None))

    if city:
        query = query.filter(Sale.city == city)

    return [row[0] for row in query.distinct().order_by(Sale.type).all() if row[0]]


def get_clients(
    db: Session,
    city: str | None = None,
    filters: list | None = None,
) -> list[str]:
    query = db.query(Sale.client).filter(Sale.client.isnot(None))

    if city:
        query = query.filter(Sale.city == city)

    if filters:
        query = query.filter(*filters)

    return [row[0] for row in query.distinct().order_by(Sale.client).all() if row[0]]
