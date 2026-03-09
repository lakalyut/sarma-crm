import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from .auth_models import (
    PasswordToken,
    SessionModel,
    User,
    default_expiry,
    new_session_id,
)
from .auth_security import hash_password, verify_password
from .database import get_db
from .templating import templates

router = APIRouter(prefix="/auth", tags=["auth"])


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()

    user = db.query(User).filter(User.email == email).first()
    if not user or not user.is_active or not user.password_hash:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Неверный логин или пароль"},
        )

    if not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Неверный логин или пароль"},
        )

    sid = new_session_id()
    sess = SessionModel(
        id=sid, user_id=user.id, expires_at=default_expiry(hours=24 * 14)
    )
    db.add(sess)
    db.commit()

    resp = RedirectResponse(url="/", status_code=HTTP_302_FOUND)
    resp.set_cookie(
        "session_id",
        sid,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        path="/",
    )
    return resp


@router.post("/logout")
def logout(db: Session = Depends(get_db), request: Request = None):
    sid = request.cookies.get("session_id") if request else None
    if sid:
        db.query(SessionModel).filter(SessionModel.id == sid).delete()
        db.commit()

    resp = RedirectResponse(url="/auth/login", status_code=HTTP_302_FOUND)
    resp.delete_cookie("session_id", path="/")
    return resp


@router.get("/set-password")
def set_password_form(request: Request, token: str):
    return templates.TemplateResponse(
        "auth/set_password.html", {"request": request, "token": token}
    )


@router.post("/set-password")
def set_password(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password2:
        return templates.TemplateResponse(
            "auth/set_password.html",
            {"request": request, "token": token, "error": "Пароли не совпадают"},
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/set_password.html",
            {"request": request, "token": token, "error": "Пароль слишком короткий"},
        )

    th = sha256_hex(token)
    pt = (
        db.query(PasswordToken)
        .filter(PasswordToken.token_hash == th, PasswordToken.used_at.is_(None))
        .first()
    )
    if not pt:
        return templates.TemplateResponse(
            "auth/set_password.html",
            {
                "request": request,
                "token": token,
                "error": "Ссылка недействительна или устарела",
            },
        )

    expires_at = _as_utc_aware(pt.expires_at)
    if expires_at < datetime.now(UTC):
        return templates.TemplateResponse(
            "auth/set_password.html",
            {
                "request": request,
                "token": token,
                "error": "Ссылка недействительна или устарела",
            },
        )

    user = db.query(User).filter(User.id == pt.user_id).first()
    if not user or not user.is_active:
        return templates.TemplateResponse(
            "auth/set_password.html",
            {"request": request, "token": token, "error": "Пользователь не найден"},
        )

    user.password_hash = hash_password(password)
    pt.used_at = datetime.now(UTC)

    db.commit()

    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "message": "Пароль установлен. Теперь войдите."},
    )
