"""Rename a city's string key consistently across all related records."""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import CityRegion, EventLog, Sale, Visit

CITY_MODELS = (Sale, Visit, User, CityRegion, EventLog)


class EmptyCityConflict(ValueError):
    """The target exists without sales or visits; explicit completion is possible."""


def _city_key(name: str) -> str:
    return " ".join(name.split()).casefold()


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


def rename_city(
    db: Session, old_name: str, new_name: str, *, complete_rename: bool = False
) -> None:
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
    source_names = [city for city in cities if _city_key(city) == _city_key(old_name)]
    target_names = [
        city
        for city in cities
        if city not in source_names and _city_key(city) == _city_key(new_name)
    ]
    if target_names:
        if any(
            db.query(model.id).filter(model.city.in_(target_names)).first()
            for model in (Sale, Visit)
        ):
            raise ValueError(
                "Город с таким названием уже существует и содержит продажи или визиты."
            )
        if not complete_rename:
            raise EmptyCityConflict(
                "Город с таким названием уже существует, но не содержит продаж или визитов. "
                "Можно завершить переименование, перенеся данные в это название."
            )

    names = source_names + target_names
    assignments = (
        db.query(CityRegion)
        .filter(CityRegion.city.in_(names))
        .order_by(CityRegion.id)
        .all()
    )
    if len({row.region_id for row in assignments}) > 1:
        raise ValueError(
            "Варианты города привязаны к разным регионам. Сначала задайте одинаковый регион."
        )

    try:
        # The string key is unique here; coalesce duplicate equivalent assignments
        # before updating their names. Prefer the existing destination assignment.
        keeper = next((row for row in assignments if row.city in target_names), None)
        if keeper is None and assignments:
            keeper = assignments[0]
        for row in assignments:
            if row is not keeper:
                db.delete(row)
        db.flush()
        for model in CITY_MODELS:
            db.query(model).filter(model.city.in_(names)).update(
                {model.city: new_name}, synchronize_session="fetch"
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
