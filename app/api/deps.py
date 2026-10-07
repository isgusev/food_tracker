"""DI-обёртки FastAPI: аутентификация и сборка сервисов из сессии БД."""
from __future__ import annotations


from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import SessionDep, get_session
from app.models.household import HouseholdMember
from app.models.user import User
from app.repositories.household import HouseholdRepository, MemberRepository
from app.repositories.plan import PlanRepository
from app.repositories.stock import ShoppingListRepository, StockRepository
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
from app.services.household import HouseholdService
from app.services.plan import PlanService
from app.services.stock import StockService
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


# --- СЕМЬЯ ---
def get_household_service(session: SessionDep) -> HouseholdService:
    return HouseholdService(
        households=HouseholdRepository(session), members=MemberRepository(session)
    )


HouseholdServiceDep = Annotated[HouseholdService, Depends(get_household_service)]


async def get_current_member(
    current_user: CurrentUserDep, service: HouseholdServiceDep
) -> HouseholdMember:
    """Член семьи текущего пользователя. Все данные (рецепты, холодильник, план)
    ограничиваются его household_id; при первом входе семья создаётся."""
    return await service.ensure_member(current_user)


CurrentMemberDep = Annotated[HouseholdMember, Depends(get_current_member)]


# --- СЕРВИСЫ ДОМЕНА ---
def get_product_service(session: SessionDep) -> ProductService:
    return ProductService(
        products=ProductRepository(session),
        categories=ProductCategoryRepository(session),
        brands=BrandRepository(session),
        manufacturers=ManufacturerRepository(session),
        variants=VariantRepository(session),
        recipes=RecipeRepository(session),
    )


def get_stock_service(session: SessionDep) -> StockService:
    return StockService(
        stock=StockRepository(session),
        lists=ShoppingListRepository(session),
        plan=PlanRepository(session),
        recipes=RecipeRepository(session),
    )


def get_recipe_service(session: SessionDep) -> RecipeService:
    return RecipeService(
        recipes=RecipeRepository(session),
        categories=RecipeCategoryRepository(session),
        cooking_logs=CookingLogRepository(session),
        variants=VariantRepository(session),
        plan=PlanRepository(session),
        stock=get_stock_service(session),
    )


def get_plan_service(session: SessionDep) -> PlanService:
    return PlanService(
        plan=PlanRepository(session),
        recipes=RecipeRepository(session),
        cooking_logs=CookingLogRepository(session),
        variants=VariantRepository(session),
        members=MemberRepository(session),
        stock=get_stock_service(session),
    )


ProductServiceDep = Annotated[ProductService, Depends(get_product_service)]
RecipeServiceDep = Annotated[RecipeService, Depends(get_recipe_service)]
PlanServiceDep = Annotated[PlanService, Depends(get_plan_service)]
StockServiceDep = Annotated[StockService, Depends(get_stock_service)]
