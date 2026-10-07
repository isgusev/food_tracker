"""Репозиторий пользователей."""
from __future__ import annotations


from datetime import datetime

from sqlalchemy import func, select

from app.models.user import RegistrationInvite, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_username(self, search_username: str) -> User | None:
        stmt = select(User).where(User.search_username == search_username)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_email(self, search_email: str) -> User | None:
        stmt = select(User).where(User.search_email == search_email)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def count(self) -> int:
        return int((await self._session.execute(select(func.count(User.id)))).scalar_one())


class InviteRepository(BaseRepository[RegistrationInvite]):
    model = RegistrationInvite

    async def active(self, code: str, now: datetime) -> RegistrationInvite | None:
        stmt = select(RegistrationInvite).where(
            RegistrationInvite.code == code,
            RegistrationInvite.used_by_user_id.is_(None),
            RegistrationInvite.expires_at > now,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def by_code(self, code: str) -> RegistrationInvite | None:
        stmt = select(RegistrationInvite).where(RegistrationInvite.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def for_household(self, household_id: int) -> list[RegistrationInvite]:
        stmt = (
            select(RegistrationInvite)
            .where(RegistrationInvite.household_id == household_id)
            .order_by(RegistrationInvite.id.desc())
            .limit(50)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def created_by(self, user_id: int) -> list[RegistrationInvite]:
        stmt = (
            select(RegistrationInvite)
            .where(RegistrationInvite.created_by_user_id == user_id, RegistrationInvite.household_id.is_(None))
            .order_by(RegistrationInvite.id.desc())
            .limit(50)
        )
        return list((await self._session.execute(stmt)).scalars().all())
