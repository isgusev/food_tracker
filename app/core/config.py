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
    # Аварийный полный override URL (например, sqlite+aiosqlite:///./dev.db для демо
    # без Docker). В норме не задаётся — URL собирается из POSTGRES_* выше.
    database_url_override: str | None = None

    # --- Безопасность ---
    secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    access_token_expire_minutes: int = 60 * 24
    algorithm: str = "HS256"

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # --- Регистрация ---
    # "invite" — только по одноразовому коду приглашения (для хостинга);
    # "open" — свободная регистрация (локальная разработка, тесты)
    registration_mode: str = "invite"
    # Код для самой первой регистрации на пустой базе (пока нет ни одного
    # пользователя) — задаётся секретом на хостинге, дальше не работает
    first_invite_code: str | None = None
    invite_ttl_days: int = 7

    # --- Защита входа: не больше N неудачных попыток за окно (минуты) ---
    login_max_failures: int = 10
    login_window_minutes: int = 15

    def validate_runtime(self) -> None:
        """Проверки, которые нельзя выразить декларативно (запускается в lifespan)."""
        if self.registration_mode not in ("invite", "open"):
            raise RuntimeError("REGISTRATION_MODE должен быть invite или open")
        if self.is_production and self.registration_mode != "invite":
            raise RuntimeError("В production регистрация только по приглашениям (REGISTRATION_MODE=invite)")
        if self.is_production and self.secret_key == "CHANGE_ME_IN_PRODUCTION":
            raise RuntimeError(
                "SECRET_KEY не задан: сгенерируйте его командой "
                "`openssl rand -hex 32` и пропишите в .env. "
                "Запуск с секретом по умолчанию в production запрещён."
            )

    @property
    def database_url(self) -> str:
        """Async URL для приложения (asyncpg)."""
        if self.database_url_override:
            return self.database_url_override
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
