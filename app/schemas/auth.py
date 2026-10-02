"""Схемы аутентификации (Pydantic v2)."""
from __future__ import annotations


from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # лимит bcrypt

    @field_validator("username")
    @classmethod
    def _strip_username(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Имя пользователя не может быть пустым")
        return v


class UserResponse(ORMModel):
    id: int
    username: str
    email: str
    is_active: bool
    is_admin: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserInDB(BaseModel):
    """Внутренний объект сервиса: пользователь вместе с хэшем пароля.

    Наружу (в HTTP-ответ) всегда отдаётся только UserResponse — хэш утечь не может.
    """

    id: int
    username: str
    email: str
    hashed_password: str
    is_active: bool
    is_admin: bool
