"""Rename a city's string key consistently across all related records."""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import CityRegion, EventLog, Sale, Visit

CITY_MODELS = (Sale, Visit, User, CityRegion, EventLog)


def get_all_cities(db: Session) -> list[str]:
    # Include cities whose sales were removed and ambassadors awaiting an import.
    return sorted(
        {
            city
            for model in CITY_MODELS
            for (city,) in db.query(model.city).distinct()
            if city and city.strip()
        }
    )


def rename_city(db: Session, old_name: str, new_name: str) -> None:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Введите новое название города.")
    if len(new_name) > 200 or any(ord(char) < 32 for char in new_name):
        raise ValueError("Название должно быть до 200 символов и без переносов строк.")
    cities = get_all_cities(db)
    if old_name not in cities:
        raise ValueError("Город не найден. Обновите страницу и выберите город заново.")
    if old_name == new_name:
        raise ValueError("Новое название совпадает с текущим.")
    if any(
        city != old_name and city.strip().casefold() == new_name.casefold()
        for city in cities
    ):
        raise ValueError("Город с таким названием уже существует.")

    try:
        for model in CITY_MODELS:
            db.query(model).filter(model.city == old_name).update(
                {model.city: new_name}, synchronize_session="fetch"
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
