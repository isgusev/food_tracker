"""Общие схемы Pydantic v2."""
from __future__ import annotations


from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    """База для ответов, сконструированных из ORM-объектов (Pydantic v2)."""

    model_config = ConfigDict(from_attributes=True)
