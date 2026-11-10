"""Базовый асинхронный репозиторий: единственная точка доступа к ORM-сессии."""
from __future__ import annotations


from collections.abc import Sequence
from decimal import Decimal
from typing import Generic, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tolerance(self, household_id: int) -> Decimal:
        """Допуск семьи (кастрюля и упаковки, Household.portion_tolerance) долей 0…1."""
        from app.models.household import Household  # модели импортируют Base — без цикла
        pct = await self._session.scalar(select(Household.portion_tolerance).where(Household.id == household_id))
        return Decimal(15 if pct is None else pct) / 100

    async def get(self, pk: int) -> ModelT | None:
        return await self._session.get(self.model, pk)

    async def list(self, stmt: Select) -> Sequence[ModelT]:
        result = await self._session.execute(stmt)
        return result.scalars().all()

    def add(self, obj: ModelT) -> ModelT:
        self._session.add(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self._session.delete(obj)

    async def flush(self) -> None:
        """Применяет изменения к БД в текущей транзакции (id становятся доступны).

        commit делает Unit of Work на границе запроса (см. app/db/session.py).
        """
        await self._session.flush()
