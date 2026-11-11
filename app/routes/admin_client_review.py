"""Administrator review of possible duplicate client names."""

from typing import Literal
from urllib.parse import unquote, urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_303_SEE_OTHER

from ..auth_deps import require_admin
from ..database import get_db
from ..observability import log_action
from ..render import render
from ..services.cities_service import get_all_cities
from ..services.client_name_review_service import (
    assign_missing_client_type,
    dismiss_names,
    get_client_type_gaps,
    get_review_cities,
    get_review_groups,
    get_review_point_types,
    merge_names,
    preview_merge,
)

router = APIRouter(prefix="/admin/clients/review", tags=["admin-client-review"])
_REVIEW_URL = "/admin/clients/review"
_PAGE_SIZE = 50


def _render_review(request, db, city, page=1, **context):
    cities = get_review_cities(db)
    city = city if city in cities or (city and city in get_all_cities(db)) else ""
    groups = get_review_groups(db, city) if city else []
    type_gaps = get_client_type_gaps(db, city) if city else []
    pages = max(1, (len(groups) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(max(page, 1), pages)
    start = (page - 1) * _PAGE_SIZE
    return render(
        request,
        "admin/client_name_review.html",
        {
            "title": "Ревизия клиентов — Пульс",
            "cities": cities,
            "selected_city": city,
            "groups": groups[start : start + _PAGE_SIZE],
            "group_count": len(groups),
            "type_gaps": type_gaps,
            "point_types": get_review_point_types(db, city) if type_gaps else [],
            "page": page,
            "pages": pages,
            **context,
        },
    )


@router.get("")
def client_name_review(
    request: Request,
    city: str = "",
    page: int = 1,
    sales: int | None = None,
    visits: int | None = None,
    dismissed: bool = False,
    assigned: int | None = None,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    return _render_review(
        request,
        db,
        city,
        page,
        sales=sales,
        visits=visits,
        dismissed=dismissed,
        assigned=assigned,
    )


@router.post("")
def review_client_names(
    request: Request,
    city: str = Form(...),
    variants: list[str] = Form(default=[]),
    canonical: str = Form(""),
    operation: Literal["preview", "merge", "dismiss"] = Form(...),
    expected_sales: int = Form(-1),
    expected_visits: int = Form(-1),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    names = [unquote(name) for name in variants]
    try:
        if operation == "preview":
            plan = preview_merge(db, city, names, canonical)
            return render(
                request,
                "admin/client_name_merge_preview.html",
                {"title": "Объединение клиентов — Пульс", "city": city, "plan": plan},
            )
        if operation == "dismiss":
            dismiss_names(db, city, names)
            log_action("client_names_dismissed", user_id=admin.id, city=city)
            result = {"dismissed": 1}
        else:
            plan = merge_names(
                db,
                city,
                names,
                canonical,
                expected_counts=(expected_sales, expected_visits),
            )
            result = {"sales": plan["sales"], "visits": plan["visits"]}
            log_action("client_names_merged", user_id=admin.id, city=city, **result)
    except ValueError as exc:
        db.rollback()
        response = _render_review(request, db, city, error=str(exc))
        response.status_code = 400
        return response
    return RedirectResponse(
        f"{_REVIEW_URL}?{urlencode({'city': city, **result})}",
        status_code=HTTP_303_SEE_OTHER,
    )


@router.post("/point-type")
def assign_client_point_type(
    request: Request,
    city: str = Form(...),
    client: str = Form(...),
    point_type: str = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    try:
        count = assign_missing_client_type(db, city, unquote(client), point_type)
    except ValueError as exc:
        db.rollback()
        response = _render_review(request, db, city, error=str(exc))
        response.status_code = 400
        return response
    if count:
        log_action(
            "client_point_type_assigned", user_id=admin.id, city=city, sales=count
        )
    return RedirectResponse(
        f"{_REVIEW_URL}?{urlencode({'city': city, 'assigned': count})}",
        status_code=HTTP_303_SEE_OTHER,
    )
