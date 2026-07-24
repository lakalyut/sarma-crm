from collections import defaultdict

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
    total_by_category: dict[str, int] = {c: 0 for c in ABC_CATEGORIES}
    missing_ids_by_category: dict[str, list[int]] = {c: [] for c in ABC_CATEGORIES}

    for product_id, category in rating_by_product.items():
        if category not in ABC_CATEGORIES:
            continue

        total_by_category[category] += 1

        if product_id in owned_product_ids:
            owned_by_category[category] += 1
        else:
            missing_ids_by_category[category].append(product_id)

    all_missing_ids = [pid for ids in missing_ids_by_category.values() for pid in ids]

    missing_by_category: dict[str, list] = {c: [] for c in ABC_CATEGORIES}
    if all_missing_ids:
        products = (
            db.query(Product)
            .filter(Product.id.in_(all_missing_ids), Product.is_active.is_(True))
            .order_by(Product.brand, Product.flavor)
            .all()
        )
        for product in products:
            category = rating_by_product.get(product.id)
            if category in missing_by_category:
                missing_by_category[category].append(product)

    return {
        "owned_by_category": owned_by_category,
        "total_by_category": total_by_category,
        "missing_by_category": missing_by_category,
        "rating_by_product": rating_by_product,
    }


def get_abc_badges_for_clients(
    db: Session,
    city: str,
    sale_type: str,
    clients: list[str],
    segment_id: int,
) -> dict[str, dict[str, list[int]]]:
    if not clients:
        return {}

    ratings = (
        db.query(ProductAbcRating)
        .filter(ProductAbcRating.segment_id == segment_id)
        .all()
    )
    rating_by_product = {r.product_id: r.category for r in ratings}

    total_by_category: dict[str, int] = {c: 0 for c in ABC_CATEGORIES}
    for category in rating_by_product.values():
        if category in total_by_category:
            total_by_category[category] += 1

    owned_rows = (
        db.query(Sale.client, Sale.product_id)
        .filter(
            Sale.city == city,
            Sale.type == sale_type,
            Sale.client.in_(clients),
            Sale.product_id.isnot(None),
        )
        .distinct()
        .all()
    )

    owned_by_client: dict[str, set[int]] = defaultdict(set)
    for row in owned_rows:
        owned_by_client[row.client].add(row.product_id)

    badges: dict[str, dict[str, list[int]]] = {}
    for client in clients:
        owned_ids = owned_by_client.get(client, set())
        owned_by_category = {c: 0 for c in ABC_CATEGORIES}

        for product_id in owned_ids:
            category = rating_by_product.get(product_id)
            if category in owned_by_category:
                owned_by_category[category] += 1

        badges[client] = {
            c: [owned_by_category[c], total_by_category[c]] for c in ABC_CATEGORIES
        }

    return badges
