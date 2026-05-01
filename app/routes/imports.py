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
from ..services.sales_options_service import get_months, get_types

router = APIRouter()


@router.get("/api/imports/delete-options")
def import_delete_options(
    city: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return JSONResponse(
        {
            "months": get_months(db, city=city, reverse=True),
            "types": get_types(db, city=city),
        }
    )


@router.get("/import-xlsx")
def import_xlsx_form(
    request: Request,
    _admin: User = Depends(require_admin),
):
    return render(request, "imports/import_xlsx.html", {})


@router.post("/import-xlsx")
async def import_xlsx(
    request: Request,
    city: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    content = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        return render(
            request,
            "imports/import_xlsx.html",
            {"error": f"Ошибка чтения XLSX: {e}"},
        )

    required = ["Месяц", "Тип", "Клиент", "Номенклатура", "SKU", "Количество", "Вес"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return render(
            request,
            "imports/import_xlsx.html",
            {"error": f'Нет колонок: {", ".join(missing)}'},
        )

    df["Количество"] = pd.to_numeric(df["Количество"], errors="coerce").fillna(0)
    df["Вес"] = pd.to_numeric(df["Вес"], errors="coerce").fillna(0)

    products = db.query(Product).filter(Product.is_active.is_(True)).all()

    imported = 0
    unmatched = 0

    for _, row in df.iterrows():
        raw_name = str(row["Номенклатура"])
        raw_sku = str(row["SKU"])
        p, _score = match_product_by_flavor(raw_name, products)

        sale = Sale(
            city=city,
            month=str(row["Месяц"]),
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

    return render(
        request,
        "imports/import_xlsx.html",
        {
            "message": f"Импортировано строк: {imported}, не сопоставлено: {unmatched}",
        },
    )
