"""Ревизия номенклатуры — сверка сопоставленных продаж с актуальным
справочником + пересинхронизация после правки товара.
См. `services/nomenclature_review_service.py`."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..auth_deps import require_admin
from ..database import get_db
from ..render import render
from ..services.nomenclature_review_service import (
    get_drift_groups,
    resync_all,
    resync_product_sales,
)

router = APIRouter(prefix="/admin/nomenclature", tags=["admin-nomenclature"])

_REVIEW_URL = "/admin/nomenclature/review"


@router.get("/review")
def nomenclature_review(
    request: Request,
    resynced: int = -1,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    groups = get_drift_groups(db)
    return render(
        request,
        "products/nomenclature_review.html",
        {
            "title": "Ревизия номенклатуры — Пульс",
            "groups": groups,
            "total": sum(g["count"] for g in groups),
            "resynced": resynced if resynced >= 0 else None,
        },
    )


@router.post("/review/resync-all")
def nomenclature_resync_all(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    n = resync_all(db)
    return RedirectResponse(
        f"{_REVIEW_URL}?resynced={n}", status_code=HTTP_303_SEE_OTHER
    )


@router.post("/review/resync/{product_id}")
def nomenclature_resync_product(
    product_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    n = resync_product_sales(db, product_id)
    return RedirectResponse(
        f"{_REVIEW_URL}?resynced={n}", status_code=HTTP_303_SEE_OTHER
    )
