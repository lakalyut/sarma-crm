from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import EventLog, Sale
from ..render import render
from ..services.admin_workspace_service import recent_imports
from ..services.cities_service import delete_empty_city, get_empty_cities
from ..services.sale_filters import build_sale_filters
from ..services.sales_options_service import get_cities, get_months, get_types

router = APIRouter()


def _delete_page(request: Request, db: Session, **extra):
    city = extra.get("selected_city", "")
    page = extra.get("history_page", 1)
    query = db.query(func.count(EventLog.id)).filter(EventLog.event_type == "import")
    if city:
        query = query.filter(EventLog.city == city)
    total = query.scalar() or 0
    history = []
    for event in recent_imports(db, city=city, limit=20, offset=(page - 1) * 20):
        event_months = [m.strip() for m in event.months.split(",") if m.strip()]
        history.append(
            {
                "event": event,
                "months": event_months,
                "selection_url": "/admin/imports?"
                + urlencode({"city": event.city, "months": event_months}, doseq=True)
                + "#delete-data",
            }
        )
    return render(
        request,
        "admin/imports_delete.html",
        {
            "title": "История и удаление импортов — Пульс",
            "import_history": history,
            "history_page": page,
            "history_total": total,
            "history_previous": (
                "/admin/imports?" + urlencode({"city": city, "history_page": page - 1})
                if page > 1
                else ""
            ),
            "history_next": (
                "/admin/imports?" + urlencode({"city": city, "history_page": page + 1})
                if page * 20 < total
                else ""
            ),
            "cities": get_cities(db),
            "months": get_months(db, city=city or None),
            "sale_types": get_types(db, city=city or None),
            "empty_cities": get_empty_cities(db),
            "selected_city": "",
            "selected_months": [],
            "selected_types": [],
            "preview_count": None,
            **extra,
        },
    )


@router.get("/admin/imports")
@router.get("/admin/imports/delete")
def imports_delete_form(
    request: Request,
    deleted_city: str = "",
    city: str = "",
    months: list[str] = Query(default=[]),
    history_page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return _delete_page(
        request,
        db,
        selected_city=city,
        selected_months=months,
        history_page=history_page,
        city_delete_message=f"Город «{deleted_city}» удалён." if deleted_city else "",
    )


@router.post("/admin/imports/delete/city")
def empty_city_delete(
    request: Request,
    city: str = Form(""),
    confirm: bool = Form(False),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    try:
        if not confirm:
            raise ValueError("Подтвердите удаление выбранного города.")
        if not city or not city.strip():
            raise ValueError("Выберите город для удаления.")
        delete_empty_city(db, city)
    except ValueError as error:
        response = _delete_page(request, db, city_delete_error=str(error))
        response.status_code = 400
        return response
    return RedirectResponse(
        "/admin/imports?" + urlencode({"deleted_city": city}), status_code=303
    )


@router.post("/admin/imports/delete/preview")
def imports_delete_preview(
    request: Request,
    city: str = Form(""),
    months: list[str] = Form(default=[]),
    sale_type: str = Form(""),
    sale_types: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    types = sale_types or ([sale_type] if sale_type else [])
    selection = {
        "selected_city": city,
        "selected_months": months,
        "selected_types": types,
    }
    if not city and not months and not types:
        return _delete_page(
            request, db, **selection, error="Укажи хотя бы один фильтр для удаления."
        )

    filters = build_sale_filters(
        city=city or None, months=months or None, sale_types=types or None
    )
    preview_count = int(db.query(func.count(Sale.id)).filter(*filters).scalar() or 0)
    return _delete_page(
        request,
        db,
        **selection,
        preview_count=preview_count,
        message=f"Найдено строк для удаления: {preview_count}",
    )


@router.post("/admin/imports/delete/confirm")
def imports_delete_confirm(
    request: Request,
    city: str = Form(""),
    months: list[str] = Form(default=[]),
    sale_type: str = Form(""),
    sale_types: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    types = sale_types or ([sale_type] if sale_type else [])
    selection = {
        "selected_city": city,
        "selected_months": months,
        "selected_types": types,
    }
    if not city and not months and not types:
        return _delete_page(
            request, db, **selection, error="Удаление без фильтров запрещено."
        )

    filters = build_sale_filters(
        city=city or None, months=months or None, sale_types=types or None
    )
    preview_count = int(db.query(func.count(Sale.id)).filter(*filters).scalar() or 0)
    if preview_count == 0:
        return _delete_page(
            request,
            db,
            **selection,
            preview_count=0,
            error="По выбранным фильтрам ничего не найдено.",
        )

    db.query(Sale).filter(*filters).delete(synchronize_session=False)
    db.commit()
    return _delete_page(request, db, message=f"Удалено строк: {preview_count}")
