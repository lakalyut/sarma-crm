import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..auth_models import PasswordToken, User, default_expiry, new_password_token


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_password_reset_link(db: Session, user: User, base_url: str) -> str:
    now = datetime.now(UTC)

    old_tokens = (
        db.query(PasswordToken)
        .filter(
            PasswordToken.user_id == user.id,
            PasswordToken.purpose == "set_password",
            PasswordToken.used_at.is_(None),
        )
        .all()
    )
    for t in old_tokens:
        t.used_at = now

    raw_token = new_password_token()
    pt = PasswordToken(
        token_hash=sha256_hex(raw_token),
        user_id=user.id,
        purpose="set_password",
        expires_at=default_expiry(hours=24 * 7),
        used_at=None,
        created_at=now,
    )
    db.add(pt)
    db.commit()

    return f"{base_url.rstrip('/')}/auth/set-password?token={raw_token}"
