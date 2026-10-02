"""Точка входа FastAPI-приложения."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.error_handlers import register_error_handlers
from app.api.v1.router import api_router, public_router
from app.core.config import get_settings
from app.db.session import init_db, set_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Никаких create_all в рантайме — схема живёт только в Alembic-миграциях.
    # Движок/пул соединений создаётся один раз на процесс.
    init_db(get_settings())
    try:
        yield
    finally:
        set_session_factory(None)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Учет продуктов КБЖУ",
        version="0.2.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(public_router)
    app.include_router(api_router)

    @app.get("/")
    async def read_root():
        return JSONResponse(
            content={"message": "Привет! Бэкенд запущен."},
            media_type="application/json; charset=utf-8",
        )

    return app


app = create_app()
