from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import Sale
from ..render import render
from ..services.cities_service import delete_empty_city, get_empty_cities
from ..services.sale_filters import build_sale_filters
from ..services.sales_options_service import get_cities, get_months, get_types

router = APIRouter()


def _delete_page(request: Request, db: Session, **extra):
    return render(
        request,
        "admin/imports_delete.html",
        {
            "title": "Удаление импорта — Пульс",
            "cities": get_cities(db),
            "months": get_months(db),
            "sale_types": get_types(db),
            "empty_cities": get_empty_cities(db),
            "selected_city": "",
            "selected_months": [],
            "selected_type": "",
            "preview_count": None,
            **extra,
        },
    )


@router.get("/admin/imports/delete")
def imports_delete_form(
    request: Request,
    deleted_city: str = "",
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return _delete_page(
        request,
        db,
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
        "/admin/imports/delete?" + urlencode({"deleted_city": city}), status_code=303
    )


@router.post("/admin/imports/delete/preview")
def imports_delete_preview(
    request: Request,
    city: str = Form(""),
    months: list[str] = Form(default=[]),
    sale_type: str = Form(""),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    selection = {
        "selected_city": city,
        "selected_months": months,
        "selected_type": sale_type,
    }
    if not city and not months and not sale_type:
        return _delete_page(
            request, db, **selection, error="Укажи хотя бы один фильтр для удаления."
        )

    filters = build_sale_filters(
        city=city or None, months=months or None, sale_type=sale_type or None
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
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    selection = {
        "selected_city": city,
        "selected_months": months,
        "selected_type": sale_type,
    }
    if not city and not months and not sale_type:
        return _delete_page(
            request, db, **selection, error="Удаление без фильтров запрещено."
        )

    filters = build_sale_filters(
        city=city or None, months=months or None, sale_type=sale_type or None
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
