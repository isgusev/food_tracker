"""DI-обёртки FastAPI: аутентификация и сборка сервисов из сессии БД."""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import get_session
from app.models.user import User
from app.repositories.diary import DiaryRepository
from app.repositories.product import (
    BrandRepository,
    ManufacturerRepository,
    ProductCategoryRepository,
    ProductRepository,
    VariantRepository,
)
from app.repositories.recipe import (
    CookingLogRepository,
    RecipeCategoryRepository,
    RecipeRepository,
)
from app.repositories.user import UserRepository
from app.services.auth import AuthService
from app.services.diary import DiaryService
from app.services.product import ProductService
from app.services.recipe import RecipeService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- АУТЕНТИФИКАЦИЯ ---
# auto_error=False: сами превращаем отсутствие/битый токен в доменную 401
bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_service(session: SessionDep) -> AuthService:
    return AuthService(users=UserRepository(session))


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: AuthServiceDep,
) -> User:
    """Проверяет Bearer-JWT и загружает пользователя из БД.

    Загружаем каждый запрос (а не доверяем claims): деактивированный аккаунт
    теряет доступ мгновенно, без отзыва токенов.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Требуется авторизация (Bearer token)")

    payload = decode_access_token(credentials.credentials)
    if payload is None or "sub" not in payload:
        raise UnauthorizedError("Недействительный или истёкший токен")

    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise UnauthorizedError("Некорректный формат токена") from None

    user = await service.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Пользователь не найден или отключён")

    # для тестов/отладки можно временно отключить проверку прав
    request.state.current_user = user
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def require_admin(current_user: CurrentUserDep) -> User:
    if not current_user.is_admin:
        raise ForbiddenError("Требуются права администратора")
    return current_user


AdminUserDep = Annotated[User, Depends(require_admin)]


# --- СЕРВИСЫ ДОМЕНА ---
def get_product_service(session: SessionDep) -> ProductService:
    return ProductService(
        products=ProductRepository(session),
        categories=ProductCategoryRepository(session),
        brands=BrandRepository(session),
        manufacturers=ManufacturerRepository(session),
        variants=VariantRepository(session),
    )


def get_recipe_service(session: SessionDep) -> RecipeService:
    return RecipeService(
        recipes=RecipeRepository(session),
        categories=RecipeCategoryRepository(session),
        cooking_logs=CookingLogRepository(session),
        variants=VariantRepository(session),
        diary=DiaryRepository(session),
    )


def get_diary_service(session: SessionDep) -> DiaryService:
    return DiaryService(
        diary=DiaryRepository(session),
        recipes=RecipeRepository(session),
        cooking_logs=CookingLogRepository(session),
    )


ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]
RecipeServiceDep = Annotated[RecipeService, Depends(get_recipe_service)]
DiaryServiceDep = Annotated[DiaryService, Depends(get_diary_service)]
