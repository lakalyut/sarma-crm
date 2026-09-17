"""Горизонт 13 — мини-апп амбассадора: подтверждение личности (Этап 2) и сам
визит — выбор клиента/типа точки/ароматов (Этап 3).

Доступ расширен на роль `user` (запрос 2026-09-16, доработано 2026-09-17)
— аналитику тоже нужен бот, но без привязки к одному городу (в браузере он
и так видит все города сразу). **Вкладка «Визит» у роли `user` теперь ЕСТЬ
(полный мини-апп, «для демонстрации функционала», решение пользователя) —
но визит не пишется в БД (`create_visit(..., dry_run=True)`, «не засорять
БД»); валидация анкеты при этом та же самая, что у настоящего визита
амбассадора. Роуты ниже поэтому делятся на две группы:
- «Визит»/«Клиенты»/история по точке — общие для обеих ролей, но город
  форсится на `user.city` только для `ambassador`; `user` передаёт `city`
  явно в query/body (мини-апп сам даёт выбрать — `get_visit_options()`
  отдаёт СПИСОК городов не-амбассадору, а не один).
- «Лидерборд»/`verify`/`cities` — общие без изменений."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..auth_models import User
from ..database import get_db
from ..services.ambassador_service import (
    create_visit,
    get_client_visit_history,
    get_visit_options,
)
from ..services.clients_service import get_client_detail_data, get_clients_summary_data
from ..services.leaderboard_service import get_leaderboard
from ..services.sale_filters import build_sale_filters
from ..services.sales_options_service import get_cities
from ..telegram_auth import get_current_ambassador
from ..templating import templates

router = APIRouter()


def _resolve_city(user: User, city: str | None) -> str | None:
    """Амбассадор — всегда свой город, query игнорируется (тот же принцип,
    что был здесь и раньше). `user` — только из query, своего фиксированного
    города у него нет."""
    return user.city if user.role == "ambassador" else city


@router.get("/ambassador/app", response_class=HTMLResponse)
def ambassador_app_page(request: Request):
    return templates.TemplateResponse("ambassador/app.html", {"request": request})


@router.post("/ambassador/app/verify")
def ambassador_app_verify(user: User = Depends(get_current_ambassador)):
    return {
        "ok": True,
        "role": user.role,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "city": user.city,
    }


@router.get("/ambassador/app/cities")
def ambassador_app_cities(
    _user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """Список городов под пикеры «Клиентов»/«Визита» у роли `user` —
    амбассадору не нужен (у него город фиксирован), но эндпоинт не гейтим
    ролью — не секрет, тот же список, что и на всех фильтрах региона в
    браузере."""
    return {"cities": get_cities(db)}


@router.get("/ambassador/app/leaderboard")
def ambassador_app_leaderboard(
    _user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    return {"rows": get_leaderboard(db)}


@router.get("/ambassador/app/options")
def ambassador_app_options(
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """Амбассадор — один свой город (как раньше). `user` — все города
    сразу (см. `get_visit_options()`): форма визита сама даёт выбрать,
    `populateCity()` в app.html уже умела показывать `<select>`, если
    городов больше одного, просто раньше не срабатывало."""
    cities = [user.city] if user.role == "ambassador" else get_cities(db)
    return get_visit_options(db, cities)


@router.get("/ambassador/app/clients")
def ambassador_app_clients(
    city: str | None = None,
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """Список (клиент, тип точки) по городу — тот же принцип форса
    city=user.city для амбассадора, что у браузерного пути
    (`/analytics/clients` под `require_client_viewer`); для роли `user` —
    город из query (мини-апп сам даёт выбрать, город не зафиксирован).
    Мини-ап аутентифицируется заголовком (`Authorization: tma`), не
    cookie-сессией — обычные аналитические роуты ему физически
    недоступны, `require_client_viewer` их не пустит."""
    target_city = _resolve_city(user, city)
    if not target_city:
        return {"rows": []}

    filters = build_sale_filters(city=target_city)
    data = get_clients_summary_data(db=db, filters=filters)
    rows = [
        {
            "client": r.client,
            "sale_type": r.type,
            "qty": float(r.qty or 0),
            "weight": float(r.weight or 0),
            "sku_count": int(r.sku_count or 0),
        }
        for r in data["rows"]
    ]
    return {"rows": rows}


@router.get("/ambassador/app/client-detail")
def ambassador_app_client_detail(
    client: str,
    sale_type: str,
    city: str | None = None,
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """`city` — `user.city` для амбассадора (query игнорируется), иначе из
    query: `client`/`sale_type` могли бы быть чем угодно, но
    `get_client_detail_data` их всё равно фильтрует вместе с городом —
    запрос на чужой/неизвестный город просто вернёт пустой результат, не
    чужие данные."""
    target_city = _resolve_city(user, city)
    if not target_city:
        return {"summary": None, "rows": []}

    data = get_client_detail_data(
        db=db, city=target_city, client=client, sale_type=sale_type
    )
    rows = [
        {
            "name": r.name,
            "sku": r.sku,
            "qty": float(r.qty or 0),
            "weight": float(r.weight or 0),
        }
        for r in data["rows"]
    ]
    return {"summary": data["summary"], "rows": rows}


@router.get("/ambassador/app/visit-history")
def ambassador_app_visit_history(
    client: str = "",
    city: str | None = None,
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    target_city = _resolve_city(user, city)
    if not client or not target_city:
        return {"history": []}
    return {"history": get_client_visit_history(db, target_city, client)}


@router.post("/ambassador/app/visits")
async def ambassador_app_create_visit(
    request: Request,
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """`dry_run` — только для роли, отличной от `ambassador` (мини-апп,
    демо-режим 2026-09-17): анкета валидируется полностью, но в БД ничего
    не пишется — визиты роли `user` нужны только показать, как работает
    функционал, не засорять реальные данные."""
    body = await request.json()

    try:
        visit = create_visit(
            db,
            user,
            city=body.get("city", ""),
            client=body.get("client", ""),
            sale_type=body.get("sale_type", ""),
            product_ids=body.get("product_ids") or [],
            sku_classic=body.get("sku_classic"),
            sku_strong=body.get("sku_strong"),
            sku_light=body.get("sku_light"),
            people_count=body.get("people_count"),
            comment=body.get("comment", ""),
            goal=body.get("goal", ""),
            dry_run=user.role != "ambassador",
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return {"ok": True, "visit_id": visit.id if visit else None, "demo": visit is None}
