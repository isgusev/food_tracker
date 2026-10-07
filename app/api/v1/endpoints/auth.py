"""Эндпоинты аутентификации: регистрация, логин (OAuth2 password flow), профиль."""
from __future__ import annotations


from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import AuthServiceDep, CurrentUserDep
from app.core.config import get_settings
from app.core.exceptions import DomainError, TooManyRequestsError, UnauthorizedError
from app.core.ratelimit import limiter
from app.schemas.auth import AuthConfig, Token, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["Аутентификация"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _guard(key: str) -> None:
    s = get_settings()
    wait = limiter.retry_after(key, s.login_max_failures, s.login_window_minutes * 60)
    if wait is not None:
        raise TooManyRequestsError(f"Слишком много неудачных попыток. Повторите через {wait // 60 + 1} мин.", wait)


@router.get("/config", response_model=AuthConfig)
async def auth_config(service: AuthServiceDep):
    """Как устроена регистрация (для экрана входа)."""
    s = get_settings()
    return AuthConfig(
        registration_mode=s.registration_mode,
        needs_first_user=s.registration_mode == "invite" and await service.users_count() == 0,
    )


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(user_in: UserCreate, service: AuthServiceDep, request: Request):
    """Регистрация. В режиме приглашений нужен одноразовый код (он гаснет)."""
    key = f"register:{_client_ip(request)}"
    _guard(key)
    try:
        return await service.register(user_in, get_settings())
    except DomainError:
        limiter.fail(key)   # подбор кодов приглашения тоже ограничен
        raise


async def _authenticate(service, identifier: str, password: str, request: Request):
    key = f"login:{_client_ip(request)}:{identifier.strip().lower()}"
    _guard(key)
    try:
        user = await service.authenticate(identifier, password)
    except UnauthorizedError:
        limiter.fail(key)
        raise
    limiter.reset(key)
    return user


@router.post("/token", response_model=Token)
async def login(
    service: AuthServiceDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    request: Request,
):
    """Стандартный OAuth2 password flow: username = логин (username или email).

    Совместим с кнопкой Authorize в Swagger UI и с простыми HTTP-клиентами UI.
    """
    user = await _authenticate(service, form.username, form.password, request)
    token = service.issue_token(user)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
async def login_json(
    request: Request,
    service: AuthServiceDep,
    identifier: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    """То же, что /token, но без обязательного scope — удобнее для Streamlit-UI."""
    if not identifier.strip() or not password:
        raise UnauthorizedError("Укажите учётные данные")
    user = await _authenticate(service, identifier, password, request)
    return Token(access_token=service.issue_token(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUserDep):
    return current_user
