"""Агрегатор версий API: /api/v1/..."""
from __future__ import annotations


from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1.endpoints import auth, diary, products, recipes

# Публичный срез: аутентификация
public_router = APIRouter(prefix="/api/v1")
public_router.include_router(auth.router)

# Защищённый срез: всё остальное требует валидный Bearer-JWT
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(get_current_user)])
api_router.include_router(products.router)
api_router.include_router(recipes.router)
api_router.include_router(diary.router)
