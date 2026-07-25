from sqlalchemy.orm import Session

from ..models import CityRegion, Region


def get_regions(db: Session) -> list[Region]:
    return db.query(Region).order_by(Region.sort_order, Region.id).all()


def add_region(db: Session, name: str) -> Region | None:
    name = name.strip()
    if not name:
        return None

    count = db.query(Region).count()
    region = Region(name=name, sort_order=count)
    db.add(region)
    db.commit()
    db.refresh(region)
    return region


def get_city_region_map(db: Session) -> dict[str, CityRegion]:
    return {cr.city: cr for cr in db.query(CityRegion).all()}


def save_city_assignments(db: Session, assignments: dict[str, int | None]) -> None:
    """assignments: город → id региона (None/0 — снять привязку)."""
    existing = get_city_region_map(db)

    for city, region_id in assignments.items():
        current = existing.get(city)

        if not region_id:
            if current:
                db.delete(current)
            continue

        if current:
            current.region_id = region_id
        else:
            db.add(CityRegion(city=city, region_id=region_id))

    db.commit()
