"""Горизонт 13 — мини-апп амбассадора: подтверждение личности (Этап 2) и сам
визит — выбор клиента/типа точки/ароматов (Этап 3)."""

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
from ..telegram_auth import get_current_ambassador
from ..templating import templates

router = APIRouter()


@router.get("/ambassador/app", response_class=HTMLResponse)
def ambassador_app_page(request: Request):
    return templates.TemplateResponse("ambassador/app.html", {"request": request})


@router.post("/ambassador/app/verify")
def ambassador_app_verify(user: User = Depends(get_current_ambassador)):
    return {
        "ok": True,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "city": user.city,
    }


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
    return get_visit_options(db, user.city)


@router.get("/ambassador/app/clients")
def ambassador_app_clients(
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """Список (клиент, тип точки) по городу амбассадора — тот же принцип
    вынужденного форса city=user.city, что у браузерного пути
    (`/analytics/clients` под `require_client_viewer`), только здесь
    отдельный JSON-эндпоинт: мини-ап аутентифицируется заголовком
    (`Authorization: tma`), не cookie-сессией — обычные аналитические роуты
    ему физически недоступны, `require_client_viewer` их не пустит."""
    filters = build_sale_filters(city=user.city)
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
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    """`city` — всегда `user.city`, не из query: `client`/`sale_type` могли
    бы быть чем угодно, но `get_client_detail_data` их всё равно фильтрует
    вместе с городом амбассадора — запрос на чужой город просто вернёт
    пустой результат, не чужие данные."""
    data = get_client_detail_data(
        db=db, city=user.city, client=client, sale_type=sale_type
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
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
    if not client:
        return {"history": []}
    return {"history": get_client_visit_history(db, user.city, client)}


@router.post("/ambassador/app/visits")
async def ambassador_app_create_visit(
    request: Request,
    user: User = Depends(get_current_ambassador),
    db: Session = Depends(get_db),
):
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
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return {"ok": True, "visit_id": visit.id}
