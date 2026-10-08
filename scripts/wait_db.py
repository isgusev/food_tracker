"""Ждём, пока база станет доступна (до ~60 с), и понятно пишем, что не так.

На хостинге приложение может стартовать раньше, чем поднялась база, —
вместо падения с трассировкой повторяем подключение и объясняем ошибку.
"""
from __future__ import annotations

import asyncio
import socket
import sys

import asyncpg

from app.core.config import get_settings

ATTEMPTS, DELAY = 30, 2


def explain(exc: Exception, s) -> str:
    if isinstance(exc, socket.gaierror):
        return (f"имя хоста «{s.postgres_host}» не находится. Проверьте POSTGRES_HOST: "
                "внутреннее имя со страницы «Инфо» базы (…-rw), без логина/пароля/порта, и что база запущена")
    if isinstance(exc, asyncpg.InvalidCatalogNameError):
        return f"базы «{s.postgres_db}» нет на сервере. Проверьте POSTGRES_DB (имя базы при создании кластера)"
    if isinstance(exc, asyncpg.InvalidPasswordError):
        return "неверный логин или пароль. Проверьте POSTGRES_USER / POSTGRES_PASSWORD"
    if isinstance(exc, (ConnectionRefusedError, OSError)):
        return f"сервер {s.postgres_host}:{s.postgres_port} не принимает соединения. Проверьте POSTGRES_PORT и статус базы"
    return f"{type(exc).__name__}: {exc}"


async def main() -> int:
    s = get_settings()
    if s.database_url_override:
        return 0
    ssl = s.postgres_ssl or "prefer"
    for attempt in range(1, ATTEMPTS + 1):
        try:
            conn = await asyncpg.connect(
                host=s.postgres_host, port=s.postgres_port, user=s.postgres_user,
                password=s.postgres_password, database=s.postgres_db, ssl=ssl, timeout=10,
            )
            await conn.close()
            print(f"[wait_db] база доступна (попытка {attempt})", flush=True)
            return 0
        except Exception as exc:  # noqa: BLE001 — объясняем любую причину
            print(f"[wait_db] попытка {attempt}/{ATTEMPTS}: {explain(exc, s)}", flush=True)
            await asyncio.sleep(DELAY)
    print("[wait_db] база так и не стала доступна — останавливаемся", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
