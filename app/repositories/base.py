"""Базовый асинхронный репозиторий: единственная точка доступа к ORM-сессии."""
from __future__ import annotations


from collections.abc import Sequence
from typing import Generic, TypeVar

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
