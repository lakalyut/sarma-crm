"""Ревизия номенклатуры — сверка сопоставленных продаж с актуальным
справочником.

`Sale` хранит копию SKU товара (`sale.sku`), проставленную при импорте/матче.
`edit_product` меняет `Product.canonical_sku`, но `sale.sku` не трогает → вся
аналитика через `sku_expr()` (`coalesce(Sale.sku, …)` первым) показывает старое
имя после правки бренда/линии. Здесь — детект (`sale.sku` ≠ актуальный
`canonical_sku`) и пересинхронизация.

Всё считается **в SQL** (GROUP BY / UPDATE) — таблица `sales` на бою большая,
грузить её в ORM целиком нельзя (ловили OOM). `sale.name` намеренно не
сверяем/не чиним: в `sku_expr` он 4-й после `sku`/`raw_sku`, у сопоставленных
строк не участвует, а точный пересчёт требует пер-строчного разбора веса из
`raw_name`."""

from collections import defaultdict

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ..models import Product, Sale


def _drift_cond():
    """SQL-условие «sale.sku разошёлся с товаром» (NULL-safe)."""
    return (Sale.matched.is_(True)) & (
        Sale.sku.is_(None) | (Sale.sku != Product.canonical_sku)
    )


def product_drift_count(db: Session, product_id: int) -> int:
    canon = db.query(Product.canonical_sku).filter(Product.id == product_id).scalar()
    if not canon:
        return 0
    return (
        db.query(func.count(Sale.id))
        .filter(
            Sale.product_id == product_id,
            Sale.matched.is_(True),
            Sale.sku.is_(None) | (Sale.sku != canon),
        )
        .scalar()
        or 0
    )


def get_drift_groups(db: Session) -> list[dict]:
    """Сопоставленные строки с устаревшим `sale.sku`, сгруппированные по
    товару: сколько строк, какие старые SKU встречаются, в каких городах."""
    counts = dict(
        db.query(Sale.product_id, func.count(Sale.id))
        .join(Product, Product.id == Sale.product_id)
        .filter(_drift_cond())
        .group_by(Sale.product_id)
        .all()
    )
    if not counts:
        return []

    # distinct-комбо (товар, старый sku, город) по дрейфующим строкам —
    # результат маленький (обычно 1-2 товара после правки)
    old_by_pid: dict[int, set] = defaultdict(set)
    cities_by_pid: dict[int, set] = defaultdict(set)
    for pid, sku, city in (
        db.query(Sale.product_id, Sale.sku, Sale.city)
        .join(Product, Product.id == Sale.product_id)
        .filter(_drift_cond())
        .distinct()
        .all()
    ):
        old_by_pid[pid].add(sku or "—")
        if city:
            cities_by_pid[pid].add(city)

    products = {
        p.id: p for p in db.query(Product).filter(Product.id.in_(counts.keys()))
    }

    result = [
        {
            "product": products[pid],
            "count": cnt,
            "old_names": sorted(old_by_pid[pid]),
            "cities": sorted(cities_by_pid[pid]),
        }
        for pid, cnt in counts.items()
        if pid in products
    ]
    result.sort(key=lambda g: -g["count"])
    return result


def resync_product_sales(db: Session, product_id: int) -> int:
    canon = db.query(Product.canonical_sku).filter(Product.id == product_id).scalar()
    if not canon:
        return 0
    res = db.execute(
        update(Sale)
        .where(
            Sale.product_id == product_id,
            Sale.matched.is_(True),
            Sale.sku.is_(None) | (Sale.sku != canon),
        )
        .values(sku=canon)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount or 0


def resync_all(db: Session) -> int:
    """Один `UPDATE … FROM products` — компилируется и в Postgres, и в SQLite
    (3.33+). Без пер-товарного цикла и без скана `sales` на каждый товар."""
    res = db.execute(
        update(Sale)
        .where(
            Sale.product_id == Product.id,
            Sale.matched.is_(True),
            Sale.sku.is_(None) | (Sale.sku != Product.canonical_sku),
        )
        .values(sku=Product.canonical_sku)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount or 0


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
