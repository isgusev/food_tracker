"""ORM-модель пользователя."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False)
    # canonical (lower) поля — для case-insensitive уникальности без trigram-индексов
    search_username = Column(String(50), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    search_email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class AuthGroup(Base):
    """Группа разрешений (RBAC). Права задаются списком строк-permissions."""

    __tablename__ = "auth_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    permissions = Column(String(255), nullable=False, default="")


class UserGroup(Base):
    """Членство пользователя в группе (связь многие-ко-многим users ↔ auth_groups)."""

    __tablename__ = "user_groups"

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    group_id = Column(
        Integer, ForeignKey("auth_groups.id", ondelete="CASCADE"), primary_key=True
    )
    granted_at = Column(DateTime, server_default=func.now())
