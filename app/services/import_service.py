"""Bounded batch inserts and an atomic sales/import-log transaction."""

from itertools import islice

import pandas as pd
from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..models import Product, Sale
from ..observability import import_phase, log_action
from ..product_parser import ProductMatcher, build_canonical_name, extract_weight
from .analytics_settings_service import get_matching_settings
from .client_name_review_service import get_client_aliases, lock_client_names
from .event_log_service import log_import
from .point_type_mapping_service import (
    get_point_type_mappings,
    get_point_types,
    save_point_type_mappings,
    source_point_type,
)

IMPORT_COLUMNS = ["Месяц", "Тип", "Клиент", "Номенклатура", "SKU", "Количество", "Вес"]
IMPORT_BATCH_SIZE = 1000


class UnmappedPointTypes(ValueError):
    def __init__(self, counts: dict[str, int]):
        self.counts = counts


def import_sales(
    db: Session,
    df: pd.DataFrame,
    city: str,
    user_id: int,
    *,
    type_choices: dict[str, str] | None = None,
) -> tuple[int, int]:
    with import_phase("prepare_columns"):
        df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0)
        df["Вес"] = pd.to_numeric(df["Вес"], errors="coerce").fillna(0)
    with import_phase("prepare_catalog"):
        matcher = ProductMatcher(
            db.query(Product).filter(Product.is_active.is_(True)).all(),
            min_score=get_matching_settings(db)["product_similarity"],
        )

    imported = unmatched = 0
    months = set()
    rows = iter(df[IMPORT_COLUMNS].itertuples(index=False, name=None))
    try:
        lock_client_names(db, city)
        mappings = get_point_type_mappings(db, city)
        point_types = get_point_types(db)
        counts = df["Тип"].map(source_point_type).value_counts().to_dict()
        unresolved = {
            source: int(count)
            for source, count in counts.items()
            if source not in mappings and source not in point_types
        }
        choices = {
            source: target
            for source, target in (type_choices or {}).items()
            if source in unresolved and target in point_types
        }
        missing = {
            source: count
            for source, count in unresolved.items()
            if source not in choices
        }
        if missing:
            raise UnmappedPointTypes(unresolved)
        save_point_type_mappings(db, city, choices, mappings)
        mappings.update(choices)
        aliases = get_client_aliases(db, city)
        while chunk := list(islice(rows, IMPORT_BATCH_SIZE)):
            batch = []
            with import_phase("match_and_build_rows"):
                for month, sale_type, client, raw_name, raw_sku, qty, weight in chunk:
                    raw_name = str(raw_name)
                    product, _ = matcher.match(raw_name)
                    month = str(month)
                    client = str(client)
                    source_type = source_point_type(sale_type)
                    months.add(month)
                    batch.append(
                        {
                            "city": city,
                            "month": month,
                            "type": mappings.get(source_type, source_type),
                            "raw_point_type": str(sale_type),
                            "client": aliases.get(client, client),
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
    log_action(
        "sales_imported",
        user_id=user_id,
        rows_imported=imported,
        rows_unmatched=unmatched,
    )
    return imported, unmatched
