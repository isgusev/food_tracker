"""Схемы семьи и её членов (Pydantic v2)."""
from __future__ import annotations


from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class Targets(BaseModel):
    """Личные цели КБЖУ на день (любое поле можно не задавать)."""

    calories: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("20000"))
    proteins: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2000"))
    fats: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2000"))
    carbs: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2000"))


def _clean_name(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Имя не может быть пустым")
    return v


class MemberCreate(BaseModel):
    """Член семьи без аккаунта (ребёнок и т. п.)."""

    name: str = Field(min_length=1, max_length=50)
    targets: Targets = Targets()

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _clean_name(v)


class MemberUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=50)
    targets: Optional[Targets] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else _clean_name(v)


class MemberResponse(BaseModel):
    id: int
    name: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    is_active: bool
    is_me: bool = False
    targets: Targets


class HouseholdResponse(ORMModel):
    id: int
    name: str
    invite_code: str
    monthly_budget: Optional[Decimal] = None
    me_member_id: int
    members: list[MemberResponse]


class HouseholdUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        return _clean_name(v)


class JoinRequest(BaseModel):
    invite_code: str = Field(min_length=4, max_length=16)

    @field_validator("invite_code")
    @classmethod
    def _norm(cls, v: str) -> str:
        return v.strip().upper()
