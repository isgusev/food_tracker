"""Пакет схем Pydantic. Совместимый алиас ``app.schemas`` для старого кода."""
from __future__ import annotations


from app.schemas import diary, product, recipe
from app.schemas.common import ORMModel

__all__ = ["ORMModel", "diary", "product", "recipe"]
