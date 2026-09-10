"""Горизонт 13.5, доп. заход — админ правит и удаляет визиты амбассадоров.

Точка входа — колонка «Действия» на вкладке «Анализ визита»
(`/analytics/client-analysis?tab=visit_analysis`), видна только админу.
Город визита и амбассадора не меняем — правится клиент/тип точки/анкета/
ароматы/дата (см. `ambassador_service.update_visit`)."""

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_admin
from ..database import get_db
from ..models import Visit
from ..render import render
from ..services.ambassador_service import (
    ambassador_display_name,
    delete_visit,
    get_visit_options,
    get_visit_product_ids,
    update_visit,
)

router = APIRouter(prefix="/admin/visits", tags=["admin-visits"])

_FALLBACK_BACK = "/analytics/client-analysis?tab=visit_analysis"


def _safe_back(raw: str | None, city: str) -> str:
    """Куда вернуться после сохранения/удаления. Реферер вкладки «Анализ
    визита» — как есть (сохраняет фильтры периода/клиентов), иначе — вкладка
    с уже выбранным регионом визита."""
    if raw and raw.startswith("/analytics/client-analysis"):
        return raw
    return f"{_FALLBACK_BACK}&city={city}"


def _num(value) -> str:
    return "" if value is None else str(value)


def _edit_context(
    db: Session,
    visit: Visit,
    *,
    back_url: str,
    error: str | None = None,
    form: dict | None = None,
) -> dict:
    options = get_visit_options(db, visit.city)
    fields = form or {
        "client": visit.client,
        "sale_type": visit.sale_type,
        "sku_classic": _num(visit.sku_classic),
        "sku_strong": _num(visit.sku_strong),
        "sku_light": _num(visit.sku_light),
        "people_count": _num(visit.people_count),
        "comment": visit.comment or "",
        "goal": visit.goal or "",
        "visit_date": visit.created_at.strftime("%Y-%m-%d"),
        "product_ids": get_visit_product_ids(db, visit.id),
    }
    return {
        "title": "Редактирование визита — Пульс",
        "visit": visit,
        "ambassador_name": ambassador_display_name(visit.ambassador),
        "clients": options["clients_by_city"].get(visit.city, []),
        "types": options["types_by_city"].get(visit.city, []),
        "products": options["products"],
        "visit_goals": options["visit_goals"],
        "back_url": back_url,
        "error": error,
        "f": fields,
    }


@router.get("/{visit_id}/edit")
def visit_edit_form(
    visit_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    visit = db.get(Visit, visit_id)
    if not visit:
        return RedirectResponse(_FALLBACK_BACK, status_code=HTTP_302_FOUND)

    back_url = _safe_back(request.headers.get("referer"), visit.city)
    return render(
        request, "admin/visit_edit.html", _edit_context(db, visit, back_url=back_url)
    )


@router.post("/{visit_id}/edit")
def visit_edit_submit(
    visit_id: int,
    request: Request,
    client: str = Form(""),
    sale_type: str = Form(""),
    product_ids: list[int] = Form(default=[]),
    sku_classic: str = Form(""),
    sku_strong: str = Form(""),
    sku_light: str = Form(""),
    people_count: str = Form(""),
    comment: str = Form(""),
    goal: str = Form(""),
    visit_date: str = Form(""),
    back_url: str = Form(_FALLBACK_BACK),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    visit = db.get(Visit, visit_id)
    if not visit:
        return RedirectResponse(_FALLBACK_BACK, status_code=HTTP_302_FOUND)

    safe_back = _safe_back(back_url, visit.city)
    entered = {
        "client": client,
        "sale_type": sale_type,
        "sku_classic": sku_classic,
        "sku_strong": sku_strong,
        "sku_light": sku_light,
        "people_count": people_count,
        "comment": comment,
        "goal": goal,
        "visit_date": visit_date.strip(),
        "product_ids": product_ids,
    }

    def _reject(message: str):
        db.rollback()
        return render(
            request,
            "admin/visit_edit.html",
            _edit_context(db, visit, back_url=safe_back, error=message, form=entered),
        )

    parsed_date = None
    if visit_date.strip():
        try:
            parsed_date = date.fromisoformat(visit_date.strip())
        except ValueError:
            return _reject("Дата визита — в формате ГГГГ-ММ-ДД")

    try:
        update_visit(
            db,
            visit,
            client=client,
            sale_type=sale_type,
            product_ids=product_ids,
            sku_classic=sku_classic,
            sku_strong=sku_strong,
            sku_light=sku_light,
            people_count=people_count,
            comment=comment,
            goal=goal,
            visit_date=parsed_date,
        )
    except ValueError as exc:
        return _reject(str(exc))

    return RedirectResponse(safe_back, status_code=HTTP_302_FOUND)


@router.post("/{visit_id}/delete")
def visit_delete(
    visit_id: int,
    back_url: str = Form(_FALLBACK_BACK),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    visit = db.get(Visit, visit_id)
    if not visit:
        return RedirectResponse(_FALLBACK_BACK, status_code=HTTP_302_FOUND)

    safe_back = _safe_back(back_url, visit.city)
    delete_visit(db, visit)
    return RedirectResponse(safe_back, status_code=HTTP_302_FOUND)
