from sqlalchemy import case, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import CityPointTypeMapping, PointType, Sale

DEFAULT_POINT_TYPES = ("HoReCa", "Retail", "Другое")


def get_point_types(db: Session) -> tuple[str, ...]:
    custom = (name for (name,) in db.query(PointType.name).order_by(PointType.name_key))
    return (*DEFAULT_POINT_TYPES, *custom)


def create_point_type(db: Session, name: str) -> None:
    name = " ".join(name.split())
    key = name.casefold()
    if not name or len(name) > 100:
        raise ValueError("Введите название типа длиной от 1 до 100 символов.")
    if key == "nan" or any(ord(char) < 32 for char in name):
        raise ValueError("Введите допустимое название типа точки.")
    if key in {point_type.casefold() for point_type in DEFAULT_POINT_TYPES}:
        raise ValueError("Тип точки с таким названием уже есть.")

    db.add(PointType(name_key=key, name=name))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError("Тип точки с таким названием уже есть.") from exc


def source_point_type(value) -> str:
    raw = str(value).strip(" ")
    return "" if raw.lower() == "nan" else raw


def _source_column():
    raw = func.trim(func.coalesce(Sale.raw_point_type, Sale.type, ""))
    return case((func.lower(raw) == "nan", ""), else_=raw)


def get_point_type_mappings(db: Session, city: str) -> dict[str, str]:
    return dict(
        db.query(CityPointTypeMapping.source_type, CityPointTypeMapping.target_type)
        .filter_by(city=city)
        .all()
    )


def get_city_point_types(
    db: Session, city: str, point_types: tuple[str, ...]
) -> list[dict]:
    source = _source_column()
    counts = dict(
        db.query(source, func.count(Sale.id))
        .filter(Sale.city == city)
        .group_by(source)
        .all()
    )
    saved = get_point_type_mappings(db, city)
    return [
        {
            "source": name,
            "label": name or "Без типа",
            "count": counts.get(name, 0),
            "target": saved.get(name, name if name in point_types else ""),
        }
        for name in sorted(counts.keys() | saved.keys(), key=str.casefold)
    ]


def save_point_type_mappings(
    db: Session, city: str, choices: dict[str, str], saved: dict[str, str]
) -> int:
    """Save choices and update historical sales inside the caller's transaction."""
    updated = 0
    for source, target in choices.items():
        if saved.get(source) != target:
            db.merge(
                CityPointTypeMapping(city=city, source_type=source, target_type=target)
            )
        result = db.execute(
            update(Sale.__table__)
            .where(Sale.city == city, _source_column() == source)
            .where(Sale.type.is_distinct_from(target))
            .values(
                type=target,
                raw_point_type=func.coalesce(Sale.raw_point_type, Sale.type, ""),
            )
        )
        updated += result.rowcount
    return updated
