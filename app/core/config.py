"""Конфигурация приложения через переменные окружения (pydantic-settings).

Все настройки читаются из .env / окружения. Никаких «зашитых» строк подключения
и секретов в коде — только значения по умолчанию для локальной разработки.
"""
from __future__ import annotations


from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Приложение ---
    app_name: str = "Учет продуктов КБЖУ"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "dev"  # dev | prod

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ("prod", "production")

    # --- База данных (PostgreSQL) ---
    postgres_host: str = "localhost"
    postgres_port: int = 5433  # совпадает с docker-compose.yml (5432 часто занят на macOS)
    postgres_db: str = "food_db"
    postgres_user: str = "food_user"
    postgres_password: str = "food_password"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # --- Безопасность ---
    secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    access_token_expire_minutes: int = 60 * 24
    algorithm: str = "HS256"

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:8501", "http://localhost:3000"]

    @property
    def database_url(self) -> str:
        """Async URL для приложения (asyncpg)."""
        return self._url("postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        """Синхронный URL — только для тестов на aiosqlite-замене/утилит."""
        return self._url("postgresql")

    def _url(self, driver: str) -> str:
        return (
            f"{driver}://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Кешированный singleton настроек (используется как Depends или напрямую)."""
    return Settings()
