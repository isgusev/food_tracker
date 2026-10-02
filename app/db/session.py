"""Инфраструктура БД: движок PostgreSQL (asyncpg), фабрика сессий, DI-зависимость.

Слои выше (repositories/services/api) получают сессию ТОЛЬКО через ``get_session``,
сам движок создаётся один раз на процесс (пул соединений встроен в SQLAlchemy).
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def _split_url(sync_url: str) -> str:
    """Конвертирует обычный postgresql:// URL в async-вариант (postgresql+asyncpg://)."""
    if sync_url.startswith("postgresql+asyncpg://"):
        return sync_url
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if sync_url.startswith("postgresql+psycopg://"):
        return sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    raise ValueError(f"Ожидается PostgreSQL URL, получено: {sync_url!r}")


def create_engine_from_settings(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        _split_url(settings.database_url),
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,  # отлавливать «мёртвые» соединения после рестарта PG
    )


def _session_factory(
    settings: Settings = Depends(get_settings),
) -> async_sessionmaker[AsyncSession]:
    # Кеш движка по строке URL, чтобы ленивая инициализация не плодила пулы
    factory = getattr(_session_factory, "_cache", {}).get(settings.database_url)
    if factory is None:
        engine = create_engine_from_settings(settings)
        factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        _session_factory._cache = {  # type: ignore[attr-defined]
            **getattr(_session_factory, "_cache", {}),
            settings.database_url: factory,
        }
    return factory


async def get_session(
    session_factory: async_sessionmaker[AsyncSession] = Depends(_session_factory),
) -> AsyncGenerator[AsyncSession, None]:
    """DI-зависимость FastAPI: одна транзакционная сессия на запрос."""
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
