"""Инфраструктура тестов: in-memory PostgreSQL-совместимая БД (SQLite/aiosqlite).

Схема пересоздаётся для каждого теста (create_all — допустим в тестах, в рантайме
схема живёт только в Alembic). Числовые колонки моделей объявлены asdecimal=False,
поэтому SQLite отдаёт float без crash; Pydantic-схемы конвертируют их в Decimal.
"""

import os

# До импорта app.core.config — фиксированные тестовые настройки вместо .env
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["POSTGRES_DB"] = "test_db"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 — регистрирует таблицы в Base.metadata
from app.db.base import Base
from app.db.session import set_session_factory
from app.main import create_app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture()
async def engine() -> AsyncEngine:
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture()
async def session_factory(engine):
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    # приложение резолвит сессии через глобальный хук — подменяем его на тестовый
    set_session_factory(factory)
    yield factory
    set_session_factory(None)


@pytest_asyncio.fixture()
async def client(session_factory):
    """HTTP-клиент поверх реального ASGI-приложения (без lifespan: фабрика уже подменена)."""
    application = create_app()
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
