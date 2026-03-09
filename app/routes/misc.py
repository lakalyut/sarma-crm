from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import get_current_user
from ..database import get_db

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/")
def root(
    request: Request,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=HTTP_302_FOUND)

    if user.role == "admin":
        return RedirectResponse("/admin/products", status_code=HTTP_302_FOUND)

    return RedirectResponse("/analytics/clients", status_code=HTTP_302_FOUND)
