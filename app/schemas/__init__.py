"""Пакет схем Pydantic. Совместимый алиас ``app.schemas`` для старого кода."""
from __future__ import annotations


from app.schemas import household, plan, product, recipe
from app.schemas.common import ORMModel

__all__ = ["ORMModel", "household", "plan", "product", "recipe"]
