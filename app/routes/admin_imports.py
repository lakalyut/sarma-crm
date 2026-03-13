from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..auth_models import User
from ..database import get_db
from ..models import Sale
from ..render import render

router = APIRouter()


def build_sales_filters(city: str | None, months: list[str] | None, sale_type: str | None):
    filters = []
    if city:
        filters.append(Sale.city == city)
    if months:
        filters.append(Sale.month.in_(months))
    if sale_type:
        filters.append(Sale.type == sale_type)
    return filters


@router.get("/admin/imports/delete")
def imports_delete_form(
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    cities = [r[0] for r in db.query(Sale.city).distinct().order_by(Sale.city) if r[0]]
    all_months = [r[0] for r in db.query(Sale.month).distinct().all() if r[0]]
    sale_types = [r[0] for r in db.query(Sale.type).distinct().order_by(Sale.type) if r[0]]

    return render(
        request,
        "admin/imports_delete.html",
        {
            "cities": cities,
            "months": all_months,
            "sale_types": sale_types,
            "selected_city": "",
            "selected_months": [],
            "selected_type": "",
            "preview_count": None,
        },
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
    selected_months = months

    cities = [r[0] for r in db.query(Sale.city).distinct().order_by(Sale.city) if r[0]]
    all_months = [r[0] for r in db.query(Sale.month).distinct().all() if r[0]]
    sale_types = [r[0] for r in db.query(Sale.type).distinct().order_by(Sale.type) if r[0]]

    if not city and not selected_months and not sale_type:
        return render(
            request,
            "admin/imports_delete.html",
            {
                "cities": cities,
                "months": all_months,
                "sale_types": sale_types,
                "selected_city": city,
                "selected_months": selected_months,
                "selected_type": sale_type,
                "preview_count": None,
                "error": "Укажи хотя бы один фильтр для удаления.",
            },
        )

    filters = build_sales_filters(city or None, selected_months or None, sale_type or None)

    q = db.query(func.count(Sale.id))
    if filters:
        q = q.filter(*filters)
    preview_count = int(q.scalar() or 0)

    return render(
        request,
        "admin/imports_delete.html",
        {
            "cities": cities,
            "months": all_months,
            "sale_types": sale_types,
            "selected_city": city,
            "selected_months": selected_months,
            "selected_type": sale_type,
            "preview_count": preview_count,
            "message": f"Найдено строк для удаления: {preview_count}",
        },
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
    selected_months = months

    cities = [r[0] for r in db.query(Sale.city).distinct().order_by(Sale.city) if r[0]]
    all_months = [r[0] for r in db.query(Sale.month).distinct().all() if r[0]]
    sale_types = [r[0] for r in db.query(Sale.type).distinct().order_by(Sale.type) if r[0]]

    if not city and not selected_months and not sale_type:
        return render(
            request,
            "admin/imports_delete.html",
            {
                "cities": cities,
                "months": all_months,
                "sale_types": sale_types,
                "selected_city": city,
                "selected_months": selected_months,
                "selected_type": sale_type,
                "preview_count": None,
                "error": "Удаление без фильтров запрещено.",
            },
        )

    filters = build_sales_filters(city or None, selected_months or None, sale_type or None)

    preview_q = db.query(func.count(Sale.id))
    if filters:
        preview_q = preview_q.filter(*filters)
    preview_count = int(preview_q.scalar() or 0)

    if preview_count == 0:
        return render(
            request,
            "admin/imports_delete.html",
            {
                "cities": cities,
                "months": all_months,
                "sale_types": sale_types,
                "selected_city": city,
                "selected_months": selected_months,
                "selected_type": sale_type,
                "preview_count": 0,
                "error": "По выбранным фильтрам ничего не найдено.",
            },
        )

    delete_q = db.query(Sale)
    if filters:
        delete_q = delete_q.filter(*filters)

    delete_q.delete(synchronize_session=False)
    db.commit()

    return render(
        request,
        "admin/imports_delete.html",
        {
            "cities": cities,
            "months": all_months,
            "sale_types": sale_types,
            "selected_city": "",
            "selected_months": [],
            "selected_type": "",
            "preview_count": None,
            "message": f"Удалено строк: {preview_count}",
        },
    )