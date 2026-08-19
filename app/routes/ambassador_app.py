"""Горизонт 13 — мини-апп амбассадора: подтверждение личности (Этап 2) и сам
визит — выбор клиента/типа точки/ароматов (Этап 3)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from ..auth_models import User
from ..database import get_db
from ..services.ambassador_service import create_visit, get_visit_options
from ..services.leaderboard_service import get_leaderboard
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
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return {"ok": True, "visit_id": visit.id}
