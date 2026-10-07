"""Сервис аутентификации: регистрация, проверка учётных данных, выдача JWT.

Не знает про HTTP; исключительные ситуации выражены доменными ошибками
(ConflictError / UnauthorizedError), которые api-слой маппит в коды.
"""
from __future__ import annotations


import secrets
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.models.household import HouseholdMember
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.household import MemberRepository
from app.repositories.user import InviteRepository, UserRepository
from app.schemas.auth import UserCreate, UserInDB


class AuthService:
    def __init__(
        self,
        users: UserRepository,
        invites: InviteRepository | None = None,
        members: MemberRepository | None = None,
    ) -> None:
        self._users = users
        self._invites = invites
        self._members = members

    async def _check_invite(self, data: UserCreate, settings: Settings):
        """Регистрация по приглашению: обычный одноразовый код или, на пустой
        базе, FIRST_INVITE_CODE с хостинга. Возвращает приглашение (или None)."""
        if settings.registration_mode != "invite":
            return None
        code = (data.invite_code or "").strip().upper()
        if not code:
            raise ValidationError("Регистрация только по приглашению — введите код")
        first = (settings.first_invite_code or "").strip().upper()
        if first and secrets.compare_digest(code, first) and await self._users.count() == 0:
            return None
        invite = await self._invites.active(code, _now())
        if invite is None:
            raise ValidationError("Код приглашения неверный, истёк или уже использован")
        return invite

    async def register(self, data: UserCreate, settings: Settings) -> User:
        invite = await self._check_invite(data, settings)
        search_username = data.username.lower()
        search_email = data.email.lower()

        if await self._users.get_by_username(search_username):
            raise ConflictError("Пользователь с таким именем уже существует")
        if await self._users.get_by_email(search_email):
            raise ConflictError("Пользователь с таким email уже существует")

        user = User(
            username=data.username,
            search_username=search_username,
            email=data.email,
            search_email=search_email,
            hashed_password=hash_password(data.password),
        )
        self._users.add(user)
        await self._users.flush()
        if invite is not None:
            # код гаснет; приглашение из семьи — сразу в эту семью
            invite.used_by_user_id = user.id
            invite.used_at = _now()
            if invite.household_id is not None:
                self._members.add(HouseholdMember(
                    household_id=invite.household_id, user_id=user.id, name=user.username
                ))
            await self._users.flush()
        return user

    async def authenticate(self, identifier: str, password: str) -> UserInDB:
        """Логин по username или email. Единый 401 при любом неверном вводе —
        чтобы не давать перечислять существующие аккаунты."""
        key = identifier.strip().lower()
        if "@" in key:
            user = await self._users.get_by_email(key)
        else:
            user = await self._users.get_by_username(key)

        if (
            user is None
            or not user.is_active
            or not verify_password(password, user.hashed_password)
        ):
            raise UnauthorizedError("Неверное имя пользователя или пароль")

        return UserInDB(
            id=user.id,
            username=user.username,
            email=user.email,
            hashed_password=user.hashed_password,
            is_active=user.is_active,
            is_admin=user.is_admin,
        )

    def issue_token(self, user: UserInDB) -> str:
        return create_access_token(subject=user.id, extra_claims={"username": user.username})

    async def users_count(self) -> int:
        return await self._users.count()

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._users.get(user_id)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
