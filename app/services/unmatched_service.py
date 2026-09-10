"""Ручное сопоставление/правка/удаление несопоставленных строк продаж
(`Sale.matched == False`). Импорт (`routes/imports.py`) матчит автоматически
через `match_product_by_flavor`; то, с чем парсер не справился, доводит
руками админ на `/admin/unmatched`."""

from sqlalchemy.orm import Session

from ..models import Product, Sale
from ..product_parser import build_canonical_name, extract_weight


def product_label(p: Product) -> str:
    """Строка для выпадающего списка/`<datalist>` — бренд, вкус, canonical SKU
    (SKU в хвосте, чтобы разрулить одинаковые «бренд — вкус» разного веса)."""
    return f"{p.brand} — {p.flavor} · {p.canonical_sku}"


def active_products(db: Session) -> list[Product]:
    return (
        db.query(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.brand, Product.flavor)
        .all()
    )


def match_sale_to_product(db: Session, sale: Sale, product: Product) -> None:
    """Привязать строку к товару — те же поля, что проставляет авто-матч в
    `routes/imports.py` (`sku`/`name` из canonical + вес из сырого названия
    или дефолтного веса товара), `matched = True`."""
    weight = extract_weight(sale.raw_name or "") or product.default_weight_g
    sale.product_id = product.id
    sale.sku = product.canonical_sku
    sale.name = build_canonical_name(product.canonical_sku, weight)
    sale.matched = True
    db.commit()


def unmatch_sale(db: Session, sale: Sale) -> None:
    sale.product_id = None
    sale.sku = None
    sale.name = None
    sale.matched = False
    db.commit()


def _num(raw, default=0.0) -> float:
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


def update_sale_fields(
    db: Session,
    sale: Sale,
    *,
    city: str,
    month: str,
    sale_type: str,
    client: str,
    qty,
    weight,
) -> None:
    sale.city = city.strip()
    sale.month = month.strip()
    sale.type = sale_type.strip()
    sale.client = client.strip()
    sale.qty = _num(qty)
    sale.weight = _num(weight)
    db.commit()


def delete_sale(db: Session, sale: Sale) -> None:
    db.delete(sale)
    db.commit()
