import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from starlette.status import HTTP_302_FOUND

from ..auth_deps import require_admin
from ..auth_models import PasswordToken, User, default_expiry, new_password_token
from ..database import get_db
from ..render import render

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@router.get("")
def users_list(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    users = db.query(User).order_by(User.id.desc()).all()
    return render(
        request,
        "admin/users_list.html",
        {"title": "Пользователи — Пульс", "users": users},
    )


@router.get("/new")
def user_new_form(
    request: Request,
    _admin=Depends(require_admin),
):
    return render(request, "admin/user_new.html", {"title": "Пользователи — Пульс"})


@router.post("/new")
def user_new_submit(
    request: Request,
    email: str = Form(...),
    role: str = Form("user"),
    telegram_id: str = Form(""),
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    email = email.strip().lower()
    if role not in ("user", "admin", "ambassador"):
        return render(
            request,
            "admin/user_new.html",
            {"title": "Пользователи — Пульс", "error": "Некорректная роль"},
        )

    exists = db.query(User).filter(User.email == email).first()
    if exists:
        return render(
            request,
            "admin/user_new.html",
            {
                "title": "Пользователи — Пульс",
                "error": "Пользователь с таким email уже существует",
            },
        )

    if role == "ambassador":
        # Амбассадор — без пароля, без ссылки установки: доступ через Telegram
        # initData (Этап 2 горизонта 13), сюда попадает только известный
        # заранее telegram_id. Имя/регион остаются пустыми до саморегистрации
        # в боте.
        telegram_id = telegram_id.strip()
        if not telegram_id.isdigit():
            return render(
                request,
                "admin/user_new.html",
                {
                    "title": "Пользователи — Пульс",
                    "error": "Для роли ambassador нужен Telegram ID (число)",
                },
            )

        telegram_id_int = int(telegram_id)
        existing_tg = db.query(User).filter(User.telegram_id == telegram_id_int).first()
        if existing_tg:
            return render(
                request,
                "admin/user_new.html",
                {
                    "title": "Пользователи — Пульс",
                    "error": "Этот Telegram ID уже привязан к другому пользователю",
                },
            )

        user = User(email=email, role=role, is_active=True, telegram_id=telegram_id_int)
        db.add(user)
        db.commit()
        db.refresh(user)

        return render(
            request,
            "admin/user_created.html",
            {
                "title": "Пользователи — Пульс",
                "email": email,
                "role": role,
                "link": None,
            },
        )

    user = User(email=email, role=role, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    raw_token = new_password_token()
    token_hash = sha256_hex(raw_token)

    pt = PasswordToken(
        token_hash=token_hash,
        user_id=user.id,
        purpose="set_password",
        expires_at=default_expiry(hours=24 * 7),
        used_at=None,
        created_at=datetime.now(UTC),
    )
    db.add(pt)
    db.commit()

    base = str(request.base_url).rstrip("/")
    link = f"{base}/auth/set-password?token={raw_token}"

    return render(
        request,
        "admin/user_created.html",
        {"title": "Пользователи — Пульс", "email": email, "role": role, "link": link},
    )


@router.post("/{user_id}/toggle-active")
def user_toggle_active(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)

    if user.id == admin.id:
        return render(
            request,
            "admin/users_list.html",
            {
                "title": "Пользователи — Пульс",
                "users": db.query(User).order_by(User.id.desc()).all(),
                "error": "Нельзя отключить самого себя.",
            },
        )

    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)


@router.post("/{user_id}/reset-link")
def user_reset_link(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)

    old_tokens = (
        db.query(PasswordToken)
        .filter(
            PasswordToken.user_id == user.id,
            PasswordToken.purpose == "set_password",
            PasswordToken.used_at.is_(None),
        )
        .all()
    )
    now = datetime.now(UTC)
    for t in old_tokens:
        t.used_at = now

    raw_token = new_password_token()
    token_hash = sha256_hex(raw_token)

    pt = PasswordToken(
        token_hash=token_hash,
        user_id=user.id,
        purpose="set_password",
        expires_at=default_expiry(hours=24 * 7),
        used_at=None,
        created_at=now,
    )
    db.add(pt)
    db.commit()

    base = str(request.base_url).rstrip("/")
    link = f"{base}/auth/set-password?token={raw_token}"

    return render(
        request,
        "admin/user_created.html",
        {
            "title": "Пользователи — Пульс",
            "email": user.email,
            "role": user.role,
            "link": link,
        },
    )


@router.post("/{user_id}/change-role")
def user_change_role(
    user_id: int,
    request: Request,
    role: str = Form(...),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)

    if role not in ("admin", "user", "ambassador"):
        return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)

    if user.id == admin.id and role != "admin":
        return render(
            request,
            "admin/users_list.html",
            {
                "title": "Пользователи — Пульс",
                "users": db.query(User).order_by(User.id.desc()).all(),
                "error": "Нельзя убрать роль admin у самого себя.",
            },
        )

    user.role = role
    db.commit()
    return RedirectResponse("/admin/users", status_code=HTTP_302_FOUND)
