"""Криптография аутентификации: хэширование паролей (bcrypt) и JWT-токены.

Модуль не знает ни про FastAPI, ни про БД — чистая утилита core-слоя.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# bcrypt выбран сознательно: argon2 требует системной библиотеки libargon2,
# которую сложно поставить на Windows. Ограничение passlib на bcrypt < 4
# снимается пином bcrypt==4.* в requirements (см. requirements.txt).
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        # повреждённый/чужой хэш в БД — считаем невалидным, не роняем запрос
        return False


def create_access_token(
    subject: str | int, expires_delta: timedelta | None = None, extra_claims: dict[str, Any] | None = None
) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {"sub": str(subject), "exp": expire}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Возвращает claims токена или None (истёк / подделан / неверный формат)."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None
