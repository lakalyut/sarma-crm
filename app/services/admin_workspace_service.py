"""Общая структура админки и SQL-счётчики качества данных."""

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session, joinedload

from ..models import EventLog, Product, Sale

ADMIN_GROUPS = [
    {
        "id": "management",
        "title": "Управление",
        "description": "Пользователи, справочники и настройки системы.",
        "links": [
            {"url": "/admin/users", "title": "Пользователи"},
            {"url": "/admin/products", "title": "Номенклатура"},
            {"url": "/admin/abc", "title": "ABC-рейтинг"},
            {"url": "/admin/regions", "title": "Регионы"},
            {"url": "/admin/updates", "title": "Обновления"},
        ],
    },
    {
        "id": "imports",
        "title": "Импорт данных",
        "description": "Загрузка продаж, история импортов и удаление данных.",
        "links": [
            {"url": "/import-xlsx", "title": "Загрузка продаж"},
            {"url": "/admin/imports", "title": "История и удаление"},
        ],
    },
    {
        "id": "quality",
        "title": "Качество данных",
        "description": "Сопоставление товаров и исправление расхождений.",
        "links": [
            {
                "url": "/admin/unmatched",
                "title": "Несопоставленные",
                "counter": "unmatched",
            },
            {
                "url": "/admin/nomenclature/review",
                "title": "Ревизия номенклатуры",
                "counter": "nomenclature",
            },
            {
                "url": "/admin/point-types/review",
                "title": "Ревизия типов точек",
                "counter": "types",
            },
        ],
    },
]


def admin_navigation(path: str) -> dict:
    active_group = None
    active_link = None
    for group in ADMIN_GROUPS:
        for link in group["links"]:
            if path == link["url"] or path.startswith(link["url"] + "/"):
                active_group, active_link = group, link
    return {
        "admin_groups": ADMIN_GROUPS,
        "admin_group": active_group,
        "admin_link": active_link,
        "admin_area": path == "/admin" or active_group is not None,
    }


def quality_counts(db: Session) -> dict:
    unmatched = (
        db.query(func.count(Sale.id)).filter(Sale.matched.is_(False)).scalar() or 0
    )
    nomenclature = (
        db.query(func.count(Sale.id))
        .join(Product, Product.id == Sale.product_id)
        .filter(
            Sale.matched.is_(True),
            Sale.sku.is_(None) | (Sale.sku != Product.canonical_sku),
        )
        .scalar()
        or 0
    )
    type_groups = (
        db.query(Sale.city, Sale.client)
        .group_by(Sale.city, Sale.client)
        .having(
            func.count(func.distinct(Sale.type))
            + func.max(Sale.type.is_(None).cast(Integer))
            > 1,
            func.count(func.nullif(Sale.type, "")) > 0,
        )
        .subquery()
    )
    types = db.query(func.count()).select_from(type_groups).scalar() or 0
    return {
        "unmatched": int(unmatched),
        "nomenclature": int(nomenclature),
        "types": int(types),
    }


def recent_imports(db: Session, city: str = "", limit: int = 10, offset: int = 0):
    query = (
        db.query(EventLog)
        .options(joinedload(EventLog.user))
        .filter(EventLog.event_type == "import")
    )
    if city:
        query = query.filter(EventLog.city == city)
    return (
        query.order_by(EventLog.created_at.desc(), EventLog.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
