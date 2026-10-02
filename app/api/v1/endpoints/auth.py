"""Эндпоинты аутентификации: регистрация, логин (OAuth2 password flow), профиль."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import AuthServiceDep, CurrentUserDep
from app.core.exceptions import UnauthorizedError
from app.schemas.auth import Token, UserCreate, UserResponse

router = APIRouter(prefix="/auth", tags=["Аутентификация"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(user_in: UserCreate, service: AuthServiceDep):
    user = await service.register(user_in)
    return user


@router.post("/token", response_model=Token)
async def login(
    service: AuthServiceDep,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
):
    """Стандартный OAuth2 password flow: username = логин (username или email).

    Совместим с кнопкой Authorize в Swagger UI и с простыми HTTP-клиентами UI.
    """
    user = await service.authenticate(form.username, form.password)
    token = service.issue_token(user)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
async def login_json(
    service: AuthServiceDep,
    identifier: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    """То же, что /token, но без обязательного scope — удобнее для Streamlit-UI."""
    if not identifier.strip() or not password:
        raise UnauthorizedError("Укажите учётные данные")
    user = await service.authenticate(identifier, password)
    return Token(access_token=service.issue_token(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUserDep):
    return current_user
