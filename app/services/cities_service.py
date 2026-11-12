"""Manage a city's string key consistently across all related records."""

import json

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ..auth_models import User, UserCity
from ..models import (
    CityPointTypeMapping,
    CityRegion,
    ClientNameAlias,
    ClientNameDismissal,
    EventLog,
    Region,
    Sale,
    Visit,
)
from .client_name_review_service import lock_client_names

CITY_MODELS = (Sale, Visit, User, CityRegion, EventLog, UserCity)
CITY_METADATA_MODELS = (ClientNameAlias, ClientNameDismissal, CityPointTypeMapping)


class EmptyCityConflict(ValueError):
    """The target exists without sales or visits; explicit completion is possible."""


def _city_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def get_all_cities(db: Session) -> list[str]:
    # Include cities whose sales were removed and ambassadors awaiting an import.
    result = sorted(
        {
            city
            for model in CITY_MODELS
            for (city,) in db.query(model.city).distinct()
            if city and city.strip()
        }
    )
    scope = db.info.get("brand_cities")
    return [city for city in result if scope is None or city in scope]


def get_empty_cities(db: Session) -> list[dict]:
    """Cities without sales or visits, including those still used by users."""
    counts = {
        model: dict(
            db.query(model.city, func.count(model.id)).group_by(model.city).all()
        )
        for model in CITY_MODELS
    }
    names = sorted(
        {name for items in counts.values() for name in items if name and name.strip()}
    )
    regions = dict(
        db.query(CityRegion.city, Region.name)
        .join(Region, CityRegion.region_id == Region.id)
        .all()
    )
    keys: dict[str, list[str]] = {}
    for name in names:
        keys.setdefault(_city_key(name), []).append(name)

    result = []
    for name in names:
        if counts[Sale].get(name) or counts[Visit].get(name):
            continue
        users = counts[User].get(name, 0)
        assignments = counts[UserCity].get(name, 0)
        hints = []
        if name != name.strip():
            hints.append("Пробелы в начале или конце названия.")
        if "  " in name:
            hints.append("Повторяющиеся пробелы.")
        if any(char.isspace() and char != " " for char in name):
            hints.append("Нестандартные пробельные символы.")
        similar = [
            json.dumps(other, ensure_ascii=False)
            for other in keys[_city_key(name)]
            if other != name
        ]
        if similar:
            hints.append(f"Похожее название: {', '.join(similar)}.")
        result.append(
            {
                "name": name,
                "display_name": json.dumps(name, ensure_ascii=False),
                "hints": " ".join(hints),
                "region": regions.get(name),
                "events": counts[EventLog].get(name, 0),
                "users": users,
                "assignments": assignments,
                "can_delete": not users and not assignments,
            }
        )
    return result


def delete_empty_city(db: Session, city: str) -> None:
    """Remove only an exact, unused city key and its administrative metadata."""
    # Do not strip or normalize: a whitespace variant may be the unwanted city.
    try:
        lock_client_names(db, city)
        for model, reason in (
            (Sale, "продажи"),
            (Visit, "визиты"),
            (User, "профили пользователей"),
            (UserCity, "назначения бренд-амбассадорам"),
        ):
            if db.query(model.id).filter(model.city == city).first():
                raise ValueError(f"Город не удалён: с ним связаны {reason}.")
        if not any(
            db.query(model.id).filter(model.city == city).first()
            for model in (CityRegion, EventLog)
        ):
            raise ValueError(
                "Город не найден. Обновите страницу и выберите город заново."
            )
        for model in (CityRegion, EventLog, *CITY_METADATA_MODELS):
            db.query(model).filter(model.city == city).delete(
                synchronize_session="fetch"
            )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _move_city_metadata(db: Session, cities: set[str], new_name: str) -> None:
    for model, key_fields, value_field, conflict in (
        (
            ClientNameAlias,
            ("source_name",),
            "canonical_name",
            "Варианты города по-разному сопоставляют одно название клиента.",
        ),
        (ClientNameDismissal, ("first_name", "second_name"), None, ""),
        (
            CityPointTypeMapping,
            ("source_type",),
            "target_type",
            "Варианты города по-разному сопоставляют один тип точки.",
        ),
    ):
        records = (
            db.query(model)
            .filter(model.city.in_(cities))
            .order_by((model.city == new_name).desc(), model.city)
        )
        seen = {}
        for row in records:
            key = tuple(getattr(row, field) for field in key_fields)
            value = getattr(row, value_field) if value_field else None
            if key in seen:
                if seen[key] != value:
                    raise ValueError(conflict)
                db.delete(row)
            else:
                seen[key] = value
        db.flush()
        db.execute(
            update(model)
            .where(model.city.in_(cities), model.city != new_name)
            .values(city=new_name)
            .execution_options(synchronize_session=False)
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
        review_cities = set(names) | {new_name}
        for city in sorted(review_cities):
            lock_client_names(db, city)
        _move_city_metadata(db, review_cities, new_name)
        # The string key is unique here; coalesce duplicate equivalent assignments
        # before updating their names. Prefer the existing destination assignment.
        keeper = next((row for row in assignments if row.city in target_names), None)
        if keeper is None and assignments:
            keeper = assignments[0]
        for row in assignments:
            if row is not keeper:
                db.delete(row)
        seen_users = set()
        for assignment in (
            db.query(UserCity).filter(UserCity.city.in_(names)).order_by(UserCity.id)
        ):
            if assignment.user_id in seen_users:
                db.delete(assignment)
            else:
                seen_users.add(assignment.user_id)
        db.flush()
        for model in CITY_MODELS:
            db.query(model).filter(model.city.in_(names)).update(
                {model.city: new_name}, synchronize_session="fetch"
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
