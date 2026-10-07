"""Точка входа FastAPI-приложения."""
from __future__ import annotations


from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.error_handlers import register_error_handlers
from app.api.v1.router import api_router, public_router
from app.core.config import get_settings
from app.db.session import SessionDep, init_db, set_session_factory

# Веб-интерфейс (Vue 3 без сборки) раздаётся этим же процессом: один origin — без CORS
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class WebFiles(StaticFiles):
    """Статика интерфейса с ревалидацией: браузер всегда сверяет ETag и после
    обновления сразу получает новые JS/CSS, а не старые из кэша."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # В production отказ от дефолтного SECRET_KEY — fail-fast, а не тихая уязвимость.
    settings.validate_runtime()
    # Никаких create_all в рантайме — схема живёт только в Alembic-миграциях.
    # Движок/пул соединений создаётся один раз на процесс.
    init_db(settings)
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

    @app.get("/", include_in_schema=False)
    async def read_root():
        return RedirectResponse(url="/app/")

    @app.get("/health")
    async def health():
        """Live-проверка процесса (без обращения к БД) — для Docker/compose healthcheck."""
        return {"status": "ok"}

    @app.get("/health/db")
    async def health_db(session: SessionDep):
        """Ready-проверка: реально ли доступно PostgreSQL-соединение из пула."""
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}

    if WEB_DIR.is_dir():
        app.mount("/app", WebFiles(directory=WEB_DIR, html=True), name="web")

    return app


app = create_app()
