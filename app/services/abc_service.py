from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import AbcSegment, Product, ProductAbcRating, Sale

DEFAULT_SEGMENTS = ["HoReCa", "Розница"]

ABC_CATEGORIES = ["A", "B", "C"]


def ensure_default_segments(db: Session) -> None:
    existing = {s.name for s in db.query(AbcSegment).all()}

    changed = False
    for i, name in enumerate(DEFAULT_SEGMENTS):
        if name not in existing:
            db.add(AbcSegment(name=name, sort_order=i))
            changed = True

    if changed:
        db.commit()


def guess_default_segment(
    segments: list[AbcSegment], sale_type: str
) -> AbcSegment | None:
    if not segments:
        return None

    sale_type_lower = (sale_type or "").lower()

    for segment in segments:
        name_lower = segment.name.lower()
        if name_lower in sale_type_lower or sale_type_lower in name_lower:
            return segment

    return segments[0]


def get_abc_matrix_data(db: Session) -> dict:
    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    products = (
        db.query(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.line, Product.brand, Product.flavor)
        .all()
    )
    ratings = db.query(ProductAbcRating).all()
    rating_map = {(r.product_id, r.segment_id): r.category for r in ratings}

    grouped: dict[str, list] = {}
    for product in products:
        line_label = product.line or "Классическая линейка"
        grouped.setdefault(line_label, []).append(product)

    return {
        "segments": segments,
        "grouped_products": grouped,
        "rating_map": rating_map,
    }


def add_segment(db: Session, name: str) -> None:
    name = name.strip()
    if not name:
        return

    exists = db.query(AbcSegment).filter(AbcSegment.name == name).first()
    if exists:
        return

    max_order = db.query(func.max(AbcSegment.sort_order)).scalar() or 0
    db.add(AbcSegment(name=name, sort_order=max_order + 1))
    db.commit()


def get_client_abc_overview(
    db: Session,
    city: str,
    client: str,
    sale_type: str,
    segment_id: int,
) -> dict:
    owned_product_ids = {
        row[0]
        for row in db.query(Sale.product_id)
        .filter(
            Sale.city == city,
            Sale.client == client,
            Sale.type == sale_type,
            Sale.product_id.isnot(None),
        )
        .distinct()
        .all()
    }

    ratings = (
        db.query(ProductAbcRating)
        .filter(ProductAbcRating.segment_id == segment_id)
        .all()
    )
    rating_by_product = {r.product_id: r.category for r in ratings}

    owned_by_category: dict[str, int] = {c: 0 for c in ABC_CATEGORIES}
    for product_id in owned_product_ids:
        category = rating_by_product.get(product_id)
        if category in owned_by_category:
            owned_by_category[category] += 1

    missing_a_ids = [
        product_id
        for product_id, category in rating_by_product.items()
        if category == "A" and product_id not in owned_product_ids
    ]

    missing_a_products = []
    if missing_a_ids:
        missing_a_products = (
            db.query(Product)
            .filter(Product.id.in_(missing_a_ids), Product.is_active.is_(True))
            .order_by(Product.brand, Product.flavor)
            .all()
        )

    total_a = sum(1 for category in rating_by_product.values() if category == "A")

    return {
        "owned_by_category": owned_by_category,
        "missing_a_products": missing_a_products,
        "total_a": total_a,
        "rating_by_product": rating_by_product,
    }
