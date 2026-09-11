"""Ревизия типов точек — детект клиентов с разными `Sale.type` от месяца к
месяцу + ручное выравнивание. См. `services/type_review_service.py`."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..auth_deps import require_admin
from ..database import get_db
from ..render import render
from ..services.type_review_service import get_type_drift_groups, resync_client_type

router = APIRouter(prefix="/admin/point-types", tags=["admin-point-types"])

_REVIEW_URL = "/admin/point-types/review"


@router.get("/review")
def type_review(
    request: Request,
    resynced: int = -1,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    groups = get_type_drift_groups(db)
    return render(
        request,
        "admin/type_review.html",
        {
            "title": "Ревизия типов точек — Пульс",
            "groups": groups,
            "total": sum(g["total_rows"] for g in groups),
            "resynced": resynced if resynced >= 0 else None,
        },
    )


@router.post("/review/resync")
def type_review_resync(
    city: str = Form(...),
    client: str = Form(...),
    correct_type: str = Form(...),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    n = resync_client_type(db, city, client, correct_type)
    return RedirectResponse(
        f"{_REVIEW_URL}?resynced={n}", status_code=HTTP_303_SEE_OTHER
    )
