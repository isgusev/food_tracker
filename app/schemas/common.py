"""Общие схемы Pydantic v2."""
from __future__ import annotations


from pydantic import BaseModel, ConfigDict

from app.domain import MEAL_ORDER, MEAL_TYPES


class ORMModel(BaseModel):
    """База для ответов, сконструированных из ORM-объектов (Pydantic v2)."""

    model_config = ConfigDict(from_attributes=True)


def meal_type(v: str | None) -> str | None:
    """Приём пищи: без пробелов и регистра, только из MEAL_TYPES."""
    if v is None:
        return v
    v = v.strip().lower()
    if v not in MEAL_TYPES:
        raise ValueError(f"meal_type должен быть одним из {list(MEAL_ORDER)}")
    return v


def meal_list(v: list[str] | None, *, empty_is_any: bool) -> list[str] | None:
    """Список приёмов пищи: без дублей, в порядке дня. None — «любые». Пустой список:
    empty_is_any — тоже «любые» (рецепт), иначе ошибка (что заполнять — хоть один приём)."""
    if v is None:
        return None
    out = [meal_type(m) for m in v]
    out = [m for m in MEAL_ORDER if m in out]
    if not out:
        if empty_is_any:
            return None
        raise ValueError("Выберите хотя бы один приём пищи")
    return out
