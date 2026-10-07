"""Period-aware assortment coverage by the point type's configured ABC segment."""

from collections import defaultdict

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..models import AbcSegment, Product, ProductAbcRating, Sale
from ..templating import format_month
from ..utils.dates import parse_month
from .abc_service import guess_default_segment
from .charts_service import sku_expr

CATEGORIES = ("A", "B", "C", "unrated")


def resolve_period(
    db: Session, city: str, month_from: str | None, month_to: str | None
) -> dict:
    raw_by_month = defaultdict(list)
    for (raw,) in db.query(Sale.month).filter(Sale.city == city).distinct():
        parsed = parse_month(raw)
        if parsed:
            raw_by_month[f"{parsed[0]:04d}-{parsed[1]:02d}-01"].append(raw)
    available = sorted(raw_by_month)
    if not available:
        return {"months": [], "month_from": None, "month_to": None, "raw_months": []}
    start = month_from or month_to or available[-1]
    end = month_to or month_from or available[-1]
    if start not in raw_by_month or end not in raw_by_month:
        raise ValueError("Выберите месяц с загруженными продажами этого города.")
    if start > end:
        raise ValueError("Начало периода не может быть позже окончания.")
    return {
        "months": [{"value": m, "label": format_month(m)} for m in available],
        "month_from": start,
        "month_to": end,
        "raw_months": [
            raw for m in available if start <= m <= end for raw in raw_by_month[m]
        ],
    }


def public_period(period: dict) -> dict:
    return {k: v for k, v in period.items() if k != "raw_months"}


def _catalog(db: Session):
    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    products = (
        db.query(Product).filter(Product.is_active.is_(True)).order_by(Product.id).all()
    )
    ratings = {
        (r.product_id, r.segment_id): r.category for r in db.query(ProductAbcRating)
    }
    return segments, products, ratings


def _segment_catalog(products, ratings, segment_id):
    catalog = {}
    for product in products:
        sku = (product.canonical_sku or "").strip()
        if not sku or sku in catalog:
            continue
        category = ratings.get((product.id, segment_id), "unrated")
        catalog[sku] = {
            "sku": sku,
            "name": f"{product.brand} — {product.flavor}",
            "category": category if category in CATEGORIES else "unrated",
        }
    return catalog


def _orders(db, city, raw_months, client=None, sale_type=None):
    # Product IDs may represent different pack sizes of the same canonical SKU.
    sku = func.coalesce(Product.canonical_sku, sku_expr())
    point_type = func.coalesce(Sale.type, "")
    query = (
        db.query(
            Sale.client,
            point_type.label("type"),
            sku.label("sku"),
            func.sum(case((Sale.qty > 0, Sale.qty), else_=0)).label("ordered_qty"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
        )
        .outerjoin(Product, Product.id == Sale.product_id)
        .filter(Sale.city == city, Sale.month.in_(raw_months))
    )
    if client is not None:
        query = query.filter(Sale.client == client)
    if sale_type is not None:
        query = query.filter(point_type == sale_type)
    return query.group_by(Sale.client, point_type, sku).all()


def _coverage(catalog, orders):
    counts = {c: {"ordered": 0, "total": 0} for c in CATEGORIES}
    for sku, item in catalog.items():
        counts[item["category"]]["total"] += 1
        if orders.get(sku, 0) > 0:
            counts[item["category"]]["ordered"] += 1
    extra = sum(1 for sku, qty in orders.items() if qty > 0 and sku not in catalog)
    counts["unrated"]["ordered"] += extra
    counts["unrated"]["total"] += extra
    return counts


def clients_abc(db: Session, city: str, period: dict) -> dict:
    result = {"rows": [], **public_period(period)}
    if not period["raw_months"]:
        return result
    segments, products, ratings = _catalog(db)
    orders = defaultdict(dict)
    totals = defaultdict(lambda: {"qty": 0, "weight": 0})
    for row in _orders(db, city, period["raw_months"]):
        key = (row.client, row.type)
        sku = (row.sku or "").strip()
        if sku:
            orders[key][sku] = orders[key].get(sku, 0) + float(row.ordered_qty or 0)
        totals[key]["qty"] += float(row.qty or 0)
        totals[key]["weight"] += float(row.weight or 0)
    catalogs = {}
    # Reuse the selected expression: separate COALESCE bind parameters make
    # PostgreSQL reject ORDER BY as absent from the SELECT DISTINCT list.
    point_type = func.coalesce(Sale.type, "").label("point_type")
    pairs = (
        db.query(Sale.client, point_type)
        .filter(Sale.city == city, Sale.client.isnot(None))
        .distinct()
        .order_by(Sale.client, point_type)
    )
    for client, sale_type in pairs:
        segment = guess_default_segment(segments, sale_type)
        segment_id = segment.id if segment else None
        if segment_id not in catalogs:
            catalogs[segment_id] = _segment_catalog(products, ratings, segment_id)
        key = (client, sale_type)
        result["rows"].append(
            {
                "client": client,
                "sale_type": sale_type or "",
                "segment": segment.name if segment else None,
                "abc": _coverage(catalogs[segment_id], orders[key]),
                "has_orders": any(qty > 0 for qty in orders[key].values()),
                "sku_count": sum(qty > 0 for qty in orders[key].values()),
                **totals[key],
            }
        )
    return result


def client_abc_detail(
    db: Session, city: str, client: str, sale_type: str, period: dict
) -> dict:
    result = {"abc": {}, "groups": [], "segment": None, **public_period(period)}
    # A guessed client must never expose a catalog as if it belonged to another city.
    exists = (
        db.query(Sale.id)
        .filter(
            Sale.city == city,
            Sale.client == client,
            func.coalesce(Sale.type, "") == sale_type,
        )
        .first()
    )
    if not exists or not period["raw_months"]:
        return result
    segments, products, ratings = _catalog(db)
    segment = guess_default_segment(segments, sale_type)
    catalog = _segment_catalog(products, ratings, segment.id if segment else None)
    orders = {}
    for row in _orders(db, city, period["raw_months"], client, sale_type):
        sku = (row.sku or "").strip()
        if sku:
            orders[sku] = orders.get(sku, 0) + float(row.ordered_qty or 0)
    counts = _coverage(catalog, orders)
    items = defaultdict(list)
    for sku, item in catalog.items():
        qty = orders.get(sku, 0)
        items[item["category"]].append({**item, "qty": qty, "ordered": qty > 0})
    for sku, qty in orders.items():
        if qty > 0 and sku not in catalog:
            items["unrated"].append(
                {
                    "sku": sku,
                    "name": sku,
                    "qty": qty,
                    "ordered": True,
                    "category": "unrated",
                }
            )
    result.update(
        {
            "segment": segment.name if segment else None,
            "abc": counts,
            "groups": [
                {
                    "category": c,
                    **counts[c],
                    "items": sorted(
                        items[c], key=lambda item: (not item["ordered"], item["name"])
                    ),
                }
                for c in CATEGORIES
            ],
        }
    )
    return result
