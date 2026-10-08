import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String, unique=True, index=True, nullable=False)

    password_hash = Column(String, nullable=True)
    role = Column(String, nullable=False, default="user")
    is_active = Column(Boolean, default=True, nullable=False)
    can_create_visits = Column(
        Boolean, default=False, server_default="false", nullable=False
    )
    city_assignments = relationship(
        "UserCity", cascade="all, delete-orphan", back_populates="user"
    )

    @property
    def allowed_cities(self) -> list[str]:
        if self.role != "brand_ambassador":
            return []
        return sorted(assignment.city for assignment in self.city_assignments)

    @property
    def can_record_visits(self) -> bool:
        return bool(
            self.is_active
            and (
                self.role == "ambassador"
                or (self.role == "user" and self.can_create_visits)
                or (
                    self.role == "brand_ambassador" and self.city in self.allowed_cities
                )
            )
        )

    # BigInteger, не Integer — баг поймали 2026-09-12: современные Telegram
    # ID давно перевалили за 2^31-1 (были ~5.5 млрд у реального амбассадора),
    # 32-битный Integer в Postgres на проде падал NumericValueOutOfRange при
    # попытке проставить такой id через /admin/users/{id}/edit. В SQLite
    # (dev/тесты) эта граница вообще не проверяется — тесты с маленькими
    # фиктивными id баг не поймали, только прод на реальных данных.
    telegram_id = Column(BigInteger, unique=True, nullable=True)
    telegram_chat_id = Column(BigInteger, nullable=True)
    updates_enabled = Column(
        Boolean, default=True, server_default="true", nullable=False
    )
    # Город, не макро-регион — той же природы поле, что Sale.city/Visit.city
    # (нет отдельной сущности "Город" в проекте, простая строка везде).
    city = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    events_last_seen_at = Column(DateTime(timezone=True), nullable=True)


class UserCity(Base):
    __tablename__ = "user_cities"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    city = Column(String, nullable=False)
    user = relationship("User", back_populates="city_assignments")
    __table_args__ = (UniqueConstraint("user_id", "city", name="uq_user_city"),)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)

    user = relationship("User")


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id = Column(Integer, primary_key=True, autoincrement=True)

    email = Column(String, index=True, nullable=False)
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class PasswordToken(Base):
    __tablename__ = "password_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)

    token_hash = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    purpose = Column(String, nullable=False, default="set_password")
    created_at = Column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")


def new_session_id() -> str:
    return secrets.token_urlsafe(32)


def new_password_token() -> str:
    return secrets.token_urlsafe(48)


def default_expiry(hours: int = 24) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)
