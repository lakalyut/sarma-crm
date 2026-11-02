"""Prepare optional city availability announcements for admin review."""

from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import ReleaseUpdate, Sale
from .release_update_service import validate_text


def imported_cities(db: Session) -> list[str]:
    """Only cities with imported sales, excluding empty user/region placeholders."""
    return sorted(
        city for (city,) in db.query(Sale.city).distinct() if city and city.strip()
    )


def create_city_draft(db: Session, selected: list[str]) -> ReleaseUpdate:
    available = set(imported_cities(db))
    cities = sorted(set(selected))
    if not cities or len(cities) > 30 or any(city not in available for city in cities):
        raise ValueError("Выберите от 1 до 30 городов с загруженными продажами.")
    title = "Данные по городам доступны в Пульсе"
    body = (
        "В Пульсе доступны данные по городам:\n"
        + "\n".join(f"• {city}" for city in cities)
        + "\n\nОткройте Пульс, чтобы посмотреть данные своего города."
    )
    validate_text(title, body, "all")
    update = ReleaseUpdate(release_key=f"cities-{uuid4().hex}", title=title, body=body)
    db.add(update)
    db.commit()
    db.refresh(update)
    return update
