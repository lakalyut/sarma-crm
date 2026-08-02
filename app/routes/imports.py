import io

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import Product, Sale
from ..product_parser import (
    build_canonical_name,
    extract_weight,
    match_product_by_flavor,
)
from ..render import render
from ..services.event_log_service import log_import
from ..services.sales_options_service import get_months, get_types
from ..templating import format_month

router = APIRouter()

MAX_IMPORT_FILE_SIZE = 20 * 1024 * 1024


@router.get("/api/imports/delete-options")
def import_delete_options(
    city: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    months = get_months(db, city=city, reverse=True)
    return JSONResponse(
        {
            "months": [{"value": m, "label": format_month(m)} for m in months],
            "types": get_types(db, city=city),
        }
    )


@router.get("/import-xlsx")
def import_xlsx_form(
    request: Request,
    _admin: User = Depends(require_admin),
):
    return render(request, "imports/import_xlsx.html", {"title": "Импорт XLSX — Пульс"})


@router.post("/import-xlsx")
async def import_xlsx(
    request: Request,
    city: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return render(
            request,
            "imports/import_xlsx.html",
            {
                "title": "Импорт XLSX — Пульс",
                "error": "Файл должен быть в формате .xlsx",
            },
        )

    content = await file.read()
    if len(content) > MAX_IMPORT_FILE_SIZE:
        size_mb = len(content) / (1024 * 1024)
        return render(
            request,
            "imports/import_xlsx.html",
            {
                "title": "Импорт XLSX — Пульс",
                "error": f"Файл слишком большой ({size_mb:.1f} МБ) — лимит 20 МБ.",
            },
        )

    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        return render(
            request,
            "imports/import_xlsx.html",
            {"title": "Импорт XLSX — Пульс", "error": f"Ошибка чтения XLSX: {e}"},
        )

    required = ["Месяц", "Тип", "Клиент", "Номенклатура", "SKU", "Количество", "Вес"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return render(
            request,
            "imports/import_xlsx.html",
            {
                "title": "Импорт XLSX — Пульс",
                "error": f'Нет колонок: {", ".join(missing)}',
            },
        )

    df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0)
    df["Вес"] = pd.to_numeric(df["Вес"], errors="coerce").fillna(0)

    products = db.query(Product).filter(Product.is_active.is_(True)).all()

    imported = 0
    unmatched = 0
    months_seen: set[str] = set()

    for _, row in df.iterrows():
        raw_name = str(row["Номенклатура"])
        raw_sku = str(row["SKU"])
        p, _score = match_product_by_flavor(raw_name, products)

        month = str(row["Месяц"])
        months_seen.add(month)

        sale = Sale(
            city=city,
            month=month,
            type=str(row["Тип"]),
            client=str(row["Клиент"]),
            raw_name=raw_name,
            raw_sku=raw_sku,
            qty=float(row["Количество"]),
            weight=float(row["Вес"]),
        )

        if p:
            sale.product_id = p.id
            w = extract_weight(raw_name) or p.default_weight_g
            sale.sku = p.canonical_sku
            sale.name = build_canonical_name(p.canonical_sku, w)
            sale.matched = True
        else:
            sale.matched = False
            unmatched += 1

        db.add(sale)
        imported += 1

    db.commit()

    log_import(
        db,
        city=city,
        months=sorted(months_seen),
        rows_imported=imported,
        rows_unmatched=unmatched,
        user_id=admin.id,
    )

    return render(
        request,
        "imports/import_xlsx.html",
        {
            "title": "Импорт XLSX — Пульс",
            "message": f"Импортировано строк: {imported}, не сопоставлено: {unmatched}",
        },
    )
