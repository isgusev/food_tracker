"""Схемы семьи и её членов (Pydantic v2)."""
from __future__ import annotations


from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel


class Targets(BaseModel):
    """Личные цели КБЖУ на день (любое поле можно не задавать)."""

    calories: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("20000"))
    proteins: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2000"))
    fats: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2000"))
    carbs: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("2000"))


class BodyProfile(BaseModel):
    """Параметры для расчёта целей (хранятся, чтобы не вводить каждый раз)."""

    sex: Optional[Literal["m", "f"]] = None
    birth_year: Optional[int] = Field(default=None, ge=1900, le=2100)
    height_cm: Optional[Decimal] = Field(default=None, ge=50, le=250)
    weight_kg: Optional[Decimal] = Field(default=None, ge=2, le=400)
    activity: Optional[Decimal] = Field(default=None, ge=Decimal("1.2"), le=Decimal("2.5"))
    goal: Optional[Literal["maintain", "lose", "gain"]] = None


class TargetsCalcIn(BaseModel):
    sex: Literal["m", "f"]
    birth_year: int = Field(ge=1900, le=2100)
    height_cm: Decimal = Field(gt=0, le=300)
    weight_kg: Decimal = Field(gt=0, le=500)
    activity: Decimal = Field(gt=0, le=3)
    goal: Literal["maintain", "lose", "gain"] = "maintain"


class TargetsCalcOut(BaseModel):
    targets: Targets
    age: int
    bmr: Decimal            # основной обмен, ккал
    maintenance: Decimal    # суточные траты при поддержании, ккал
    notes: list[str] = []


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
    profile: Optional[BodyProfile] = None
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
    profile: BodyProfile = BodyProfile()


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
