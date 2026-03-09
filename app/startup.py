import os

from sqlalchemy.orm import Session

from .auth_models import User
from .auth_security import hash_password


def ensure_admin(db: Session) -> None:
    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip().lower()
    admin_password = os.getenv("ADMIN_PASSWORD") or ""

    if not admin_email or not admin_password:
        return

    user = db.query(User).filter(User.email == admin_email).first()

    if not user:
        user = User(
            email=admin_email,
            password_hash=hash_password(admin_password),
            role="admin",
            is_active=True,
        )
        db.add(user)
        db.commit()
        return

    changed = False

    if user.role != "admin":
        user.role = "admin"
        changed = True

    if not user.password_hash:
        user.password_hash = hash_password(admin_password)
        changed = True

    if not user.is_active:
        user.is_active = True
        changed = True

    if changed:
        db.commit()