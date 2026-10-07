#!/bin/sh
# Старт на хостинге: сначала миграции схемы, потом сервер.
# Если миграция упала — контейнер не стартует (лучше, чем работать на старой схеме).
set -e
echo "[start] alembic upgrade head"
alembic upgrade head
echo "[start] uvicorn on :${PORT:-8000}"
# --proxy-headers: реальный IP клиента за прокси хостинга (нужен ограничителю попыток входа)
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
