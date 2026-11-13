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
    create_point_type,
    get_city_point_types,
    get_point_type_mappings,
    get_point_types,
    save_point_type_mappings,
)
from ..services.sales_options_service import get_cities, get_clients
from ..services.type_review_service import (
    get_review_cities,
    get_type_drift_groups,
    resync_client_type,
)

router = APIRouter(prefix="/admin/point-types", tags=["admin-point-types"])

_TYPES_URL = "/admin/point-types"
_REVIEW_URL = f"{_TYPES_URL}/review"
_CLIENT_TYPE_URL = f"{_TYPES_URL}/client"


def _client_type_form(request, db, city, **extra):
    cities = get_cities(db)
    return render(
        request,
        "admin/client_point_type.html",
        {
            "title": "Изменить тип точки клиента — Пульс",
            "cities": cities,
            "selected_city": city,
            "clients": (
                [
                    name
                    for name in get_clients(db, city)
                    if name.strip().casefold() not in ("", "nan")
                ]
                if city and city in cities
                else []
            ),
            "point_types": get_point_types(db),
            **extra,
        },
    )


@router.get("/client")
def client_type_form(
    request: Request,
    city: str = "",
    client: str = "",
    updated: int = -1,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return _client_type_form(request, db, city, selected_client=client, updated=updated)


@router.post("/client")
def save_client_type(
    request: Request,
    city: str = Form(...),
    client: str = Form(...),
    point_type: str = Form(...),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    if city:
        lock_client_names(db, city)
    if (
        not city
        or client.strip().casefold() in ("", "nan")
        or client not in get_clients(db, city)
        or point_type not in get_point_types(db)
    ):
        db.rollback()
        return _client_type_form(
            request,
            db,
            city,
            selected_client=client,
            error="Выберите клиента из этого города и тип точки из справочника.",
        )
    updated = resync_client_type(db, city, client, point_type)
    return RedirectResponse(
        f"{_CLIENT_TYPE_URL}?{urlencode({'city': city, 'client': client, 'updated': updated})}",
        status_code=HTTP_303_SEE_OTHER,
    )


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
def legacy_type_mapping(request: Request, _admin=Depends(require_admin)):
    query = request.url.query
    return RedirectResponse(f"{_TYPES_URL}?{query}" if query else _TYPES_URL)


@router.get("")
def type_mapping(
    request: Request,
    city: str = "",
    updated: int = -1,
    created: bool = False,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return _mapping_form(request, db, city, updated=updated, created=created)


def _mapping_form(request, db, city, **extra):
    cities = get_cities(db)
    point_types = get_point_types(db)
    return render(
        request,
        "admin/type_mapping.html",
        {
            "title": "Типы точек — Пульс",
            "cities": cities,
            "selected_city": city,
            "rows": (
                get_city_point_types(db, city, point_types) if city in cities else []
            ),
            "point_types": point_types,
            "updated": -1,
            **extra,
        },
    )


@router.post("/create")
def add_point_type(
    request: Request,
    name: str = Form(""),
    city: str = Form(""),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        create_point_type(db, name)
    except ValueError as exc:
        return _mapping_form(request, db, city, error=str(exc), entered_name=name)
    return RedirectResponse(
        f"{_TYPES_URL}?{urlencode({'city': city, 'created': 1})}",
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post("")
@router.post("/review/mapping", include_in_schema=False)
def save_type_mapping(
    request: Request,
    city: str = Form(...),
    source: list[str] = Form(...),
    target: list[str] = Form(...),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    lock_client_names(db, city)
    point_types = get_point_types(db)
    rows = get_city_point_types(db, city, point_types)
    available = {row["source"] for row in rows}
    if (
        not available
        or len(source) != len(target)
        or len(set(source)) != len(source)
        or not set(source) <= available
        or any(value and value not in point_types for value in target)
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
        f"{_TYPES_URL}?{urlencode({'city': city, 'updated': updated})}",
        status_code=HTTP_303_SEE_OTHER,
    )
