import io

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..observability import import_phase
from ..render import render
from ..services.import_service import IMPORT_COLUMNS, import_sales
from ..services.sales_options_service import get_cities, get_months, get_types
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


def _import_form(request: Request, db: Session, **extra):
    return render(
        request,
        "imports/import_xlsx.html",
        {"title": "Импорт XLSX — Пульс", "cities": get_cities(db), **extra},
    )


@router.get("/import-xlsx")
def import_xlsx_form(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return _import_form(request, db)


@router.post("/import-xlsx")
def import_xlsx(
    request: Request,
    city: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return _import_form(request, db, error="Файл должен быть в формате .xlsx")

    with import_phase("read_upload"):
        content = file.file.read(MAX_IMPORT_FILE_SIZE + 1)
    if len(content) > MAX_IMPORT_FILE_SIZE:
        return _import_form(request, db, error="Файл слишком большой — лимит 20 МБ.")

    try:
        with import_phase("parse_excel"):
            df = pd.read_excel(io.BytesIO(content))
    except Exception as e:
        return _import_form(request, db, error=f"Ошибка чтения XLSX: {e}")

    missing = [c for c in IMPORT_COLUMNS if c not in df.columns]
    if missing:
        return _import_form(request, db, error=f'Нет колонок: {", ".join(missing)}')

    imported, unmatched = import_sales(db, df, city, admin.id)

    return _import_form(
        request,
        db,
        message=f"Импортировано строк: {imported}, не сопоставлено: {unmatched}",
    )
