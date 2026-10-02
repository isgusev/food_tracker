"""Инфраструктура БД: движок PostgreSQL (asyncpg), фабрика сессий, DI-зависимость.

Слои выше (repositories/services/api) получают сессию ТОЛЬКО через ``get_session``.
Движок создаётся ОДИН раз на процесс в lifespan (см. app/main.py); тесты могут
подменить глобальный фабричный синглтон через ``set_session_factory``.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def _to_async_url(url: str) -> str:
    """Конвертирует postgresql:// URL в async-вариант (postgresql+asyncpg://)."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    raise ValueError(f"Ожидается PostgreSQL URL, получено: {url!r}")


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        _to_async_url(settings.database_url),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # отлавливать «мёртвые» соединения после рестарта PG
    )


# --- Глобальный синглтон фабрики (инициализируется в lifespan приложения) ---
_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(
            create_engine_from_settings(settings),
            expire_on_commit=False,
            autoflush=False,
        )
    return _factory


def set_session_factory(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Тестовый хук: подмена/сброс фабрики сессий."""
    global _factory
    _factory = factory


def _get_factory() -> async_sessionmaker[AsyncSession]:
    if _factory is None:
        raise RuntimeError(
            "БД не инициализирована: фабрика сессий создаётся в lifespan приложения."
        )
    return _factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """DI-зависимость FastAPI: одна транзакционная сессия (Unit of Work) на запрос."""
    async with _get_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
