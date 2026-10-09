"""Bounded batch inserts and an atomic sales/import-log transaction."""

from itertools import islice

import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..models import Product, Sale
from ..observability import import_phase
from ..product_parser import ProductMatcher, build_canonical_name, extract_weight
from .event_log_service import log_import

IMPORT_COLUMNS = ["Месяц", "Тип", "Клиент", "Номенклатура", "SKU", "Количество", "Вес"]
IMPORT_BATCH_SIZE = 1000


def import_sales(
    db: Session, df: pd.DataFrame, city: str, user_id: int
) -> tuple[int, int]:
    with import_phase("prepare_columns"):
        df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0)
        df["Вес"] = pd.to_numeric(df["Вес"], errors="coerce").fillna(0)
    with import_phase("prepare_catalog"):
        matcher = ProductMatcher(
            db.query(Product).filter(Product.is_active.is_(True)).all()
        )

    imported = unmatched = 0
    months = set()
    rows = iter(df[IMPORT_COLUMNS].itertuples(index=False, name=None))
    try:
        while chunk := list(islice(rows, IMPORT_BATCH_SIZE)):
            batch = []
            with import_phase("match_and_build_rows"):
                for month, sale_type, client, raw_name, raw_sku, qty, weight in chunk:
                    raw_name = str(raw_name)
                    product, _ = matcher.match(raw_name)
                    month = str(month)
                    months.add(month)
                    batch.append(
                        {
                            "city": city,
                            "month": month,
                            "type": str(sale_type),
                            "client": str(client),
                            "raw_name": raw_name,
                            "raw_sku": str(raw_sku),
                            "qty": float(qty),
                            "weight": float(weight),
                            "product_id": product.id if product else None,
                            "sku": product.canonical_sku if product else None,
                            "name": (
                                build_canonical_name(
                                    product.canonical_sku,
                                    extract_weight(raw_name)
                                    or product.default_weight_g,
                                )
                                if product
                                else None
                            ),
                            "matched": product is not None,
                        }
                    )
                    imported += 1
                    unmatched += product is None
            with import_phase("save_sales"):
                db.execute(insert(Sale.__table__), batch)
        with import_phase("commit_import"):
            log_import(
                db,
                city=city,
                months=sorted(months),
                rows_imported=imported,
                rows_unmatched=unmatched,
                user_id=user_id,
                commit=False,
            )
            db.commit()
    except Exception:
        db.rollback()
        raise
    return imported, unmatched
