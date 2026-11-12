"""Ревизия типов точек — детект клиентов с разными `Sale.type` от месяца к
месяцу + ручное выравнивание. См. `services/type_review_service.py`."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..auth_deps import require_admin
from ..database import get_db
from ..render import render
from ..services.client_name_review_service import lock_client_names
from ..services.point_type_mapping_service import (
    POINT_TYPES,
    get_city_point_types,
    get_point_type_mappings,
    save_point_type_mappings,
)
from ..services.sales_options_service import get_cities
from ..services.type_review_service import (
    get_review_cities,
    get_type_drift_groups,
    resync_client_type,
)

router = APIRouter(prefix="/admin/point-types", tags=["admin-point-types"])

_REVIEW_URL = "/admin/point-types/review"


@router.get("/review")
def type_review(
    request: Request,
    city: str = "",
    resynced: int = -1,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    groups = get_type_drift_groups(db, city=city or None)
    return render(
        request,
        "admin/type_review.html",
        {
            "title": "Ревизия типов точек — Пульс",
            "groups": groups,
            "cities": get_review_cities(db),
            "selected_city": city,
            "total": sum(g["total_rows"] for g in groups),
            "resynced": resynced if resynced >= 0 else None,
        },
    )


@router.post("/review/resync")
def type_review_resync(
    city: str = Form(...),
    client: str = Form(...),
    correct_type: str = Form(...),
    filter_city: str = Form(""),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    n = resync_client_type(db, city, client, correct_type)
    return RedirectResponse(
        f"{_REVIEW_URL}?{urlencode({'resynced': n, 'city': filter_city})}",
        status_code=HTTP_303_SEE_OTHER,
    )


@router.get("/review/mapping")
def type_mapping(
    request: Request,
    city: str = "",
    updated: int = -1,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return _mapping_form(request, db, city, updated=updated)


def _mapping_form(request, db, city, **extra):
    cities = get_cities(db)
    return render(
        request,
        "admin/type_mapping.html",
        {
            "title": "Типы точек по городу — Пульс",
            "cities": cities,
            "selected_city": city,
            "rows": get_city_point_types(db, city) if city in cities else [],
            "point_types": POINT_TYPES,
            "updated": -1,
            **extra,
        },
    )


@router.post("/review/mapping")
def save_type_mapping(
    request: Request,
    city: str = Form(...),
    source: list[str] = Form(...),
    target: list[str] = Form(...),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    lock_client_names(db, city)
    rows = get_city_point_types(db, city)
    available = {row["source"] for row in rows}
    if (
        not available
        or len(source) != len(target)
        or len(set(source)) != len(source)
        or not set(source) <= available
        or any(value and value not in POINT_TYPES for value in target)
    ):
        db.rollback()
        return _mapping_form(
            request,
            db,
            city,
            error="Список типов изменился или выбран недопустимый тип.",
        )
    saved = get_point_type_mappings(db, city)
    choices = {
        name: value
        for name, value in zip(source, target, strict=True)
        if value and saved.get(name) != value
    }
    updated = save_point_type_mappings(db, city, choices, saved)
    db.commit()
    return RedirectResponse(
        f"{_REVIEW_URL}/mapping?{urlencode({'city': city, 'updated': updated})}",
        status_code=HTTP_303_SEE_OTHER,
    )
