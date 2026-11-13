from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND, HTTP_404_NOT_FOUND

from ..auth_deps import get_current_user, require_analyst
from ..auth_models import User
from ..database import get_db
from ..render import render
from ..services.home_service import (
    get_city_flavor_ranking,
    get_home_overview,
    get_product_abc_by_city,
)
from ..templating import templates

router = APIRouter()


@router.get("/")
def home_page(
    request: Request,
    year: int | None = None,
    db: Session = Depends(get_db),
):
    # заменяет прежний редирект «/» (запрос 2026-09-12) — но только для
    # admin/user: снапшот по ВСЕМ городам сразу, амбассадору (или любой
    # будущей роли без блэнкет-доступа к аналитике) он не подходит —
    # у него по-прежнему прежний вход, тот же, что был раньше на «/».
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=HTTP_302_FOUND)

    if user.role not in ("admin", "user", "brand_ambassador"):
        return RedirectResponse("/analytics/clients", status_code=HTTP_302_FOUND)

    overview = get_home_overview(db, year)

    return render(
        request,
        "home.html",
        {
            "title": "Главная — Пульс",
            "empty_state": {
                "title": (
                    "Пока нет данных по назначенным городам"
                    if user.role == "brand_ambassador"
                    else "Пока нет данных"
                ),
                "hint": (
                    "Назначение городов и загрузку продаж выполняет администратор."
                    if user.role == "brand_ambassador"
                    else "Загрузите первый импорт продаж — здесь появится сводка по всему бизнесу"
                ),
            },
            **overview,
        },
    )


@router.get("/analytics/city-flavor-abc")
def city_flavor_abc(
    request: Request,
    city: str,
    year: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    return templates.TemplateResponse(
        "includes/home_flavor_rows.html",
        {
            "request": request,
            "top_flavors": get_city_flavor_ranking(db, city, year),
            "year": year,
            "flavor_city": city,
        },
    )


@router.get("/analytics/product-abc")
def product_abc_page(
    request: Request,
    product_id: int,
    year: int | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_analyst),
):
    # get_product_abc_by_city сам разрешает year (None/недоступный год —
    # последний доступный) — роут больше не ходит за available_years
    # заранее отдельным запросом (было 3 похода за месяцами на эту
    # страницу суммарно, лишние 2 убрали, фидбек «долго грузится»,
    # 2026-09-13). None возвращается только если product_id не существует.
    data = get_product_abc_by_city(db, product_id, year)
    if not data:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND)

    return render(
        request,
        "analytics/product_abc.html",
        {
            "title": f"{data['product'].flavor} — ABC по городам — Пульс",
            **data,
        },
    )
