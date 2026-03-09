from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from .auth_models import SessionModel, User
from .database import get_db


def _as_utc_aware(dt: datetime) -> datetime:
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    sid = request.cookies.get("session_id")
    if not sid:
        return None

    sess = db.query(SessionModel).filter(SessionModel.id == sid).first()
    if not sess:
        return None

    expires_at = _as_utc_aware(sess.expires_at)
    if expires_at < datetime.now(UTC):
        db.delete(sess)
        db.commit()
        return None

    user = db.query(User).filter(User.id == sess.user_id).first()
    if not user or not user.is_active:
        return None

    return user


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED)
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=HTTP_403_FORBIDDEN)
    return user