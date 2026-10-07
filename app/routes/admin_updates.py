import os

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth_deps import require_admin
from ..database import get_db
from ..models import ReleaseUpdate, UpdateDelivery
from ..render import render
from ..services import release_update_service as service

router = APIRouter(prefix="/admin/updates", dependencies=[Depends(require_admin)])


def get_update(db, update_id):
    update = db.get(ReleaseUpdate, update_id)
    if update is None:
        raise HTTPException(404)
    return update


def detail(request, db, update, error=None):
    return render(
        request,
        "admin/update_detail.html",
        {
            "title": "Обновление — Пульс",
            "update": update,
            "error": error,
            "audiences": service.AUDIENCES,
            "statuses": service.STATUSES,
            "delivery_statuses": service.DELIVERY_STATUSES,
            "counts": service.delivery_counts(db, update.id),
            "recipient_count": service.bot_users(db, update.audience)
            .filter_by(updates_enabled=True)
            .count(),
            "deliveries": db.query(UpdateDelivery)
            .filter_by(update_id=update.id)
            .order_by(UpdateDelivery.id)
            .limit(200)
            .all(),
            "preview": service.message_text(update.title, update.body),
        },
    )


@router.get("")
def updates(request: Request, db: Session = Depends(get_db)):
    return render(
        request,
        "admin/updates.html",
        {
            "title": "Обновления — Пульс",
            "statuses": service.STATUSES,
            "updates": db.query(ReleaseUpdate)
            .order_by(ReleaseUpdate.id.desc())
            .limit(100)
            .all(),
        },
    )


@router.get("/{update_id}")
def update_detail(update_id: int, request: Request, db: Session = Depends(get_db)):
    return detail(request, db, get_update(db, update_id))


@router.post("/{update_id}/edit")
def edit(
    update_id: int,
    request: Request,
    title: str = Form(""),
    body: str = Form(""),
    audience: str = Form("all"),
    db: Session = Depends(get_db),
):
    update = get_update(db, update_id)
    if update.status != "draft":
        return detail(
            request,
            db,
            update,
            "После начала рассылки текст и аудиторию менять нельзя.",
        )
    try:
        service.validate_text(title, body, audience)
    except ValueError as exc:
        return detail(request, db, update, str(exc))
    # Conditional write also protects edits racing with the Send button.
    db.query(ReleaseUpdate).filter_by(id=update_id, status="draft").update(
        {"title": title.strip(), "body": body.strip(), "audience": audience}
    )
    db.commit()
    return RedirectResponse(f"/admin/updates/{update_id}", status_code=303)


@router.post("/{update_id}/send")
def send(update_id: int, request: Request, db: Session = Depends(get_db)):
    update = get_update(db, update_id)
    if not os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_POLLING_ENABLED") != "1":
        return detail(
            request,
            db,
            update,
            "Рассылка недоступна: Telegram-бот не запущен в этой среде.",
        )
    try:
        service.queue_update(db, update_id)
    except ValueError as exc:
        db.rollback()
        return detail(request, db, get_update(db, update_id), str(exc))
    return RedirectResponse(f"/admin/updates/{update_id}", status_code=303)


@router.post("/{update_id}/retry")
def retry(update_id: int, request: Request, db: Session = Depends(get_db)):
    update = get_update(db, update_id)
    try:
        service.retry_failed(db, update_id)
    except ValueError as exc:
        db.rollback()
        return detail(request, db, update, str(exc))
    return RedirectResponse(f"/admin/updates/{update_id}", status_code=303)
