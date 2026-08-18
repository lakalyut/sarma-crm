"""Горизонт 13.1 — браузерная версия для амбассадоров (параллельно
Telegram-боту, см. ROADMAP.md: VPS не может достучаться до api.telegram.org
по исходящему HTTPS). Обычные cookie-сессии и обычный CSRF — не путать с
app/routes/ambassador_app.py (Telegram Mini App, initData-заголовок)."""

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_ambassador
from ..auth_models import User
from ..database import get_db
from ..models import Region
from ..render import render
from ..services.ambassador_service import create_visit, get_visit_options
from ..services.city_regions_service import get_regions
from ..services.leaderboard_service import get_leaderboard, get_leaderboard_months

router = APIRouter(prefix="/ambassador")


def _profile_complete(user: User) -> bool:
    return bool(user.first_name and user.region_id)


@router.get("")
def ambassador_home(user: User = Depends(require_ambassador)):
    if not _profile_complete(user):
        return RedirectResponse("/ambassador/profile", status_code=HTTP_302_FOUND)
    return RedirectResponse("/ambassador/visit", status_code=HTTP_302_FOUND)


@router.get("/profile")
def ambassador_profile_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_ambassador),
):
    return render(
        request,
        "ambassador/profile.html",
        {"title": "Анкета — Пульс", "regions": get_regions(db), "user": user},
    )


@router.post("/profile")
def ambassador_profile_submit(
    request: Request,
    first_name: str = Form(""),
    last_name: str = Form(""),
    region_id: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_ambassador),
):
    first_name = first_name.strip()
    regions = get_regions(db)

    if not first_name:
        return render(
            request,
            "ambassador/profile.html",
            {
                "title": "Анкета — Пульс",
                "regions": regions,
                "user": user,
                "error": "Введите имя",
            },
        )

    region = db.query(Region).filter(Region.id == region_id).first()
    if not region:
        return render(
            request,
            "ambassador/profile.html",
            {
                "title": "Анкета — Пульс",
                "regions": regions,
                "user": user,
                "error": "Выберите регион из списка",
            },
        )

    user.first_name = first_name
    user.last_name = last_name.strip()
    user.region_id = region.id
    db.commit()

    return RedirectResponse("/ambassador/visit", status_code=HTTP_302_FOUND)


@router.get("/visit")
def ambassador_visit_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_ambassador),
):
    if not _profile_complete(user):
        return RedirectResponse("/ambassador/profile", status_code=HTTP_302_FOUND)

    return render(
        request,
        "ambassador/visit.html",
        {
            "title": "Визит — Пульс",
            "options": get_visit_options(db, user.region_id),
        },
    )


@router.post("/visit")
def ambassador_visit_submit(
    request: Request,
    city: str = Form(""),
    client: str = Form(""),
    sale_type: str = Form(""),
    product_ids: list[int] = Form(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_ambassador),
):
    if not _profile_complete(user):
        return RedirectResponse("/ambassador/profile", status_code=HTTP_302_FOUND)

    options = get_visit_options(db, user.region_id)

    try:
        create_visit(
            db,
            user,
            city=city,
            client=client,
            sale_type=sale_type,
            product_ids=product_ids,
        )
    except ValueError as exc:
        return render(
            request,
            "ambassador/visit.html",
            {"title": "Визит — Пульс", "options": options, "error": str(exc)},
        )

    return render(
        request,
        "ambassador/visit.html",
        {
            "title": "Визит — Пульс",
            "options": get_visit_options(db, user.region_id),
            "message": "Визит записан",
        },
    )


@router.get("/leaderboard")
def ambassador_leaderboard_page(
    request: Request,
    months: list[str] = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_ambassador),
):
    if not _profile_complete(user):
        return RedirectResponse("/ambassador/profile", status_code=HTTP_302_FOUND)

    all_months = get_leaderboard_months(db)
    selected_months = [m for m in (months or []) if m in all_months]

    return render(
        request,
        "ambassador/leaderboard.html",
        {
            "title": "Лидерборд — Пульс",
            "all_months": all_months,
            "selected_months": selected_months,
            "rows": get_leaderboard(db, selected_months=selected_months or None),
            "empty_state": {
                "title": "Пока нет ни одного визита",
                "hint": "Запишите первый визит — он появится здесь и в общем лидерборде.",
            },
        },
    )
