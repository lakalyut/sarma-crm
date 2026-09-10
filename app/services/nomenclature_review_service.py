"""Ревизия номенклатуры — сверка сопоставленных продаж с актуальным
справочником.

`Sale` хранит копию названия товара (`sale.sku`/`sale.name`), проставленную
при импорте. После правки товара (`/admin/products/edit`) эти копии
устаревают: аналитика через `sku_expr()` (`coalesce(Sale.sku, …)`) начинает
показывать старое имя. Здесь — детект такого дрейфа и пересинхронизация
(пересчёт `sku`/`name` из `product_id`; `raw_name`/`raw_sku` — то, что реально
было в XLSX — не трогаем)."""

from sqlalchemy.orm import Session

from ..models import Product, Sale
from ..product_parser import build_canonical_name, extract_weight


def _wanted(sale: Sale, product: Product) -> tuple[str, str]:
    """Каким должны быть `sale.sku`/`sale.name` по актуальному товару —
    та же логика, что в `routes/imports.py` при сопоставлении."""
    weight = extract_weight(sale.raw_name or "") or product.default_weight_g
    return product.canonical_sku, build_canonical_name(product.canonical_sku, weight)


def _is_drifted(sale: Sale, product: Product) -> bool:
    want_sku, want_name = _wanted(sale, product)
    return (sale.sku or "") != want_sku or (sale.name or "") != want_name


def product_drift_count(db: Session, product_id: int) -> int:
    product = db.get(Product, product_id)
    if not product:
        return 0
    sales = db.query(Sale).filter(Sale.product_id == product_id, Sale.matched.is_(True))
    return sum(1 for s in sales if _is_drifted(s, product))


def get_drift_groups(db: Session) -> list[dict]:
    """Сопоставленные продажи с устаревшей копией названия, сгруппированные
    по товару: сколько строк, какие старые названия встречаются, в каких
    городах."""
    rows = (
        db.query(Sale, Product)
        .join(Product, Product.id == Sale.product_id)
        .filter(Sale.matched.is_(True))
        .all()
    )
    groups: dict[int, dict] = {}
    for sale, product in rows:
        if not _is_drifted(sale, product):
            continue
        g = groups.setdefault(
            product.id,
            {
                "product": product,
                "count": 0,
                "old_names": set(),
                "cities": set(),
            },
        )
        g["count"] += 1
        g["old_names"].add(sale.sku or sale.name or "—")
        if sale.city:
            g["cities"].add(sale.city)

    result = []
    for g in groups.values():
        result.append(
            {
                "product": g["product"],
                "count": g["count"],
                "old_names": sorted(g["old_names"]),
                "cities": sorted(g["cities"]),
            }
        )
    result.sort(key=lambda g: -g["count"])
    return result


def resync_product_sales(db: Session, product_id: int) -> int:
    product = db.get(Product, product_id)
    if not product:
        return 0
    updated = 0
    for sale in db.query(Sale).filter(
        Sale.product_id == product_id, Sale.matched.is_(True)
    ):
        want_sku, want_name = _wanted(sale, product)
        if (sale.sku or "") != want_sku or (sale.name or "") != want_name:
            sale.sku = want_sku
            sale.name = want_name
            updated += 1
    if updated:
        db.commit()
    return updated


def resync_all(db: Session) -> int:
    rows = (
        db.query(Sale, Product)
        .join(Product, Product.id == Sale.product_id)
        .filter(Sale.matched.is_(True))
        .all()
    )
    updated = 0
    for sale, product in rows:
        want_sku, want_name = _wanted(sale, product)
        if (sale.sku or "") != want_sku or (sale.name or "") != want_name:
            sale.sku = want_sku
            sale.name = want_name
            updated += 1
    if updated:
        db.commit()
    return updated


def flavor_collision(db: Session, product: Product) -> Product | None:
    """Другой активный товар с тем же `norm_flavor`, но другим `norm_brand` —
    типичный признак «завёл "Сарма Ваниль" вместо "Сарма 360 Ваниль"».
    Не блокирует, только предупреждение."""
    if not product.norm_flavor:
        return None
    return (
        db.query(Product)
        .filter(
            Product.id != product.id,
            Product.is_active.is_(True),
            Product.norm_flavor == product.norm_flavor,
            Product.norm_brand != product.norm_brand,
        )
        .first()
    )
