"""Репозиторий пользователей."""
from __future__ import annotations


from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_username(self, search_username: str) -> User | None:
        stmt = select(User).where(User.search_username == search_username)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, search_email: str) -> User | None:
        stmt = select(User).where(User.search_email == search_email)
        return (await self._session.execute(stmt)).scalar_one_or_none()
