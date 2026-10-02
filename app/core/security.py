"""Криптография аутентификации: хэширование паролей (bcrypt) и JWT-токены.

Модуль не знает ни про FastAPI, ни про БД — чистая утилита core-слоя.
"""

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

# --- Хэширование паролей: bcrypt напрямую (без passlib) ---
# passlib 1.7.x несовместим с bcrypt>=4.1 (падает при детекте бэкенда) и
# давно не развивается. Чтобы длинные/юникодные пароли не упирались в
# 72-байтовое ограничение bcrypt молча, секрет пред-хэшируется SHA-512 и
# передаётся в bcrypt уже в безопасной фиксированной форме (стандартный
# приём). При переходе на argon2 менять нужно только эти две функции.
_BCRYPT_MAX_INPUT = 72


def _prehash(password: str) -> bytes:
    digest = hashlib.sha512(password.encode("utf-8")).digest()
    return base64.b64encode(digest)[:_BCRYPT_MAX_INPUT]


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Пустой пароль")
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time сравнение; False при битом/чужом хэше — без исключения."""
    try:
        return bcrypt.checkpw(_prehash(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
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
