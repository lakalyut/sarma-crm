"""«Представленность SKU» — 5-я вкладка «Аналитики по клиентам».

Выбираем регион / период / тип точки (опционально) / несколько SKU → список
(клиент, тип точки) с продажами за период, у каждого подсвечено: заказал ли
клиент выбранные SKU. Зелёный — заказан хотя бы один, красный — ни одного.
Зелёные сверху. По клику — детализация клиента (`/analytics/client`)."""

from collections import defaultdict

from sqlalchemy.orm import Session

from ..models import Product, ProductAbcRating, Sale
from .ambassadors_service import get_distinct_skus
from .charts_service import sku_expr


def get_sku_options(db: Session, city: str, segment_id: int | None) -> list[dict]:
    """Список SKU для мультивыбора + бейджи ABC (по сегменту) и NEW
    (`Product.is_new`).

    Источник — **объединение**:
    - SKU из продаж города (`sku_expr()`; у сопоставленной строки это
      `Sale.sku`, т.е. `canonical_sku`, у несопоставленной — сырая строка);
    - `canonical_sku` всех активных товаров справочника — иначе только что
      заведённая номенклатура без продаж в этом городе в списке не видна
      (репорт пользователя).
    Для сырых sale-строк товар резолвится по сопоставленным продажам."""
    active_products = (
        db.query(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.brand, Product.flavor)
        .all()
    )
    product_by_sku: dict[str, Product] = {}
    for p in active_products:
        key = (p.canonical_sku or "").strip()
        if key:
            product_by_sku.setdefault(key, p)

    product_id_by_raw: dict[str, int] = {}
    for sku, product_id in (
        db.query(sku_expr().label("sku"), Sale.product_id)
        .filter(Sale.city == city, Sale.product_id.isnot(None))
        .distinct()
    ):
        key = (sku or "").strip()
        if key:
            product_id_by_raw.setdefault(key, product_id)

    is_new_by_id = {p.id: bool(p.is_new) for p in active_products}
    abc_by_id: dict[int, str] = {}
    if segment_id:
        for r in db.query(ProductAbcRating).filter(
            ProductAbcRating.segment_id == segment_id
        ):
            abc_by_id[r.product_id] = r.category

    all_skus = sorted(set(get_distinct_skus(db, city)) | set(product_by_sku.keys()))

    options = []
    for sku in all_skus:
        prod = product_by_sku.get(sku)
        pid = prod.id if prod else product_id_by_raw.get(sku)
        options.append(
            {
                "sku": sku,
                "abc": abc_by_id.get(pid) if pid else None,
                "is_new": is_new_by_id.get(pid, False) if pid else False,
            }
        )
    return options


def build_sku_presence(
    db: Session,
    city: str | None,
    selected_months: list[str],
    selected_skus: list[str],
    sale_type: str | None = None,
    qty_from: float | None = None,
    qty_to: float | None = None,
) -> dict:
    """`qty_from`/`qty_to` — диапазон по количеству, заказанному **по
    каждому выбранному SKU отдельно** — не по сумме сразу нескольких SKU
    (правка 2026-09-18: первая версия суммировала qty по всем выбранным
    SKU вместе, из-за чего клиент, взявший 3 шт. одного вкуса и 4 шт.
    другого, проходил диапазон «5-10» при сумме 7, хотя по отдельности ни
    один SKU туда не попадал — «не совсем корректно», репорт пользователя).
    Клиент проходит диапазон, если **хотя бы один** выбранный SKU у него
    в диапазоне (решение пользователя, не обязательно все сразу). Фильтр
    применяется ко всем строкам, включая красные (пустой `sku_qty`) —
    `qty_from` больше нуля естественным образом уберёт их из списка."""
    result = {"rows": [], "sku_count": len(selected_skus or []), "present_count": 0}
    if not city or not selected_skus:
        return result

    selected_set = set(selected_skus)

    query = db.query(Sale.client, Sale.type, sku_expr().label("sku"), Sale.qty).filter(
        Sale.city == city
    )
    if selected_months:
        query = query.filter(Sale.month.in_(selected_months))
    if sale_type:
        query = query.filter(Sale.type == sale_type)

    qty_by_ct_sku: dict[tuple, dict[str, float]] = defaultdict(dict)
    all_ct: set[tuple] = set()

    for client, row_type, sku, qty in query.all():
        ct = (client or "Без клиента", row_type or "")
        all_ct.add(ct)
        key = (sku or "").strip()
        if key in selected_set and (qty or 0) > 0:
            per_sku = qty_by_ct_sku[ct]
            per_sku[key] = per_sku.get(key, 0) + (qty or 0)

    def _in_range(value: float) -> bool:
        if qty_from is not None and value < qty_from:
            return False
        if qty_to is not None and value > qty_to:
            return False
        return True

    rows = []
    for client, row_type in all_ct:
        sku_qty = qty_by_ct_sku.get((client, row_type), {})
        got = set(sku_qty)
        if (qty_from is not None or qty_to is not None) and not any(
            _in_range(v) for v in sku_qty.values()
        ):
            continue
        rows.append(
            {
                "client": client,
                "sale_type": row_type,
                "ordered_skus": sorted(got),
                "missing_skus": sorted(selected_set - got),
                "ordered_count": len(got),
                "sku_qty": sku_qty,
                "is_present": bool(got),
            }
        )

    # зелёные сверху (по убыванию числа заказанных SKU), потом красные — по имени
    rows.sort(
        key=lambda r: (
            not r["is_present"],
            -r["ordered_count"],
            r["client"].lower(),
            r["sale_type"],
        )
    )
    result["rows"] = rows
    result["present_count"] = sum(1 for r in rows if r["is_present"])
    return result
