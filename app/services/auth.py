"""Сервис аутентификации: регистрация, проверка учётных данных, выдача JWT.

Не знает про HTTP; исключительные ситуации выражены доменными ошибками
(ConflictError / UnauthorizedError), которые api-слой маппит в коды.
"""
from __future__ import annotations


from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import UserCreate, UserInDB


class AuthService:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def register(self, data: UserCreate) -> User:
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

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._users.get(user_id)
