"""Горизонт 13, Этап 2 — мини-апп амбассадора: пока только подтверждение
личности (initData → имя/регион), реальный визит — Этап 3."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from ..auth_models import User
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
        "region": user.region.name if user.region else None,
    }
