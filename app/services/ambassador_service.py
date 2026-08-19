"""Горизонт 13, Этап 3 — данные и создание визита в мини-аппе амбассадора.

Амбассадор привязан к одному конкретному городу (User.city — та же природа
поле, что Sale.city/Visit.city, не отдельная сущность), не к макро-региону —
поэтому все данные визита берутся строго по этому одному городу, без
разворачивания в список городов региона."""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import AbcSegment, Product, ProductAbcRating, Visit, VisitProduct
from . import sales_options_service
from .abc_service import guess_default_segment


def get_visit_options(db: Session, city: str) -> dict:
    clients = sales_options_service.get_clients(db, city=city)
    types = sales_options_service.get_types(db, city=city)

    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    guessed_segment_by_type: dict[str, int] = {}
    for sale_type in types:
        segment = guess_default_segment(segments, sale_type)
        if segment:
            guessed_segment_by_type[sale_type] = segment.id

    needed_segment_ids = set(guessed_segment_by_type.values())
    abc_by_segment: dict[int, dict[int, str]] = {}
    if needed_segment_ids:
        ratings = (
            db.query(ProductAbcRating)
            .filter(ProductAbcRating.segment_id.in_(needed_segment_ids))
            .all()
        )
        for rating in ratings:
            abc_by_segment.setdefault(rating.segment_id, {})[
                rating.product_id
            ] = rating.category

    products = (
        db.query(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.category, Product.brand, Product.flavor)
        .all()
    )

    return {
        "cities": [city],
        "clients_by_city": {city: clients},
        "types_by_city": {city: types},
        "guessed_segment_by_type": guessed_segment_by_type,
        "abc_by_segment": abc_by_segment,
        "products": [
            {
                "id": p.id,
                "category": p.category,
                "brand": p.brand,
                "flavor": p.flavor,
                "name": p.canonical_name,
                "sku": p.canonical_sku,
            }
            for p in products
        ],
    }


def create_visit(
    db: Session,
    ambassador: User,
    city: str,
    client: str,
    sale_type: str,
    product_ids: list[int],
) -> Visit:
    if city != ambassador.city:
        raise ValueError("Вы можете записывать визиты только в своём городе")

    if client not in sales_options_service.get_clients(db, city=city):
        raise ValueError("Такого клиента нет в списке для этого города")

    if sale_type not in sales_options_service.get_types(db, city=city):
        raise ValueError("Такого типа точки нет в списке для этого города")

    if not product_ids:
        raise ValueError("Выберите хотя бы один аромат")

    valid_ids = {
        row[0]
        for row in db.query(Product.id).filter(
            Product.id.in_(product_ids), Product.is_active.is_(True)
        )
    }
    if set(product_ids) - valid_ids:
        raise ValueError("Часть выбранных ароматов недоступна, обновите страницу")

    visit = Visit(
        ambassador_id=ambassador.id, city=city, client=client, sale_type=sale_type
    )
    db.add(visit)
    db.flush()

    for product_id in product_ids:
        db.add(VisitProduct(visit_id=visit.id, product_id=product_id))

    db.commit()
    db.refresh(visit)
    return visit
