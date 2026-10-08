#!/bin/sh
# Старт на хостинге: сначала миграции схемы, потом сервер.
# Если миграция упала — контейнер не стартует (лучше, чем работать на старой схеме).
set -e
# С какими настройками подключаемся к базе (без пароля) — первая строка для диагностики
python -c "from app.core.config import get_settings as g; s = g(); print(f'[start] DB {s.postgres_user}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db} ssl={s.postgres_ssl or \"по умолчанию\"} env={s.environment} password={\"задан\" if s.postgres_password != \"food_password\" else \"НЕ ЗАДАН\"}')"
echo "[start] alembic upgrade head"
alembic upgrade head
# Порт фиксирован и совпадает с run.containerPort в amvera.yml. Переменную PORT
# не читаем: Amvera задаёт её сама (по умолчанию 80) — это развело бы порты.
echo "[start] uvicorn on :8000"
# --proxy-headers: реальный IP клиента за прокси хостинга (нужен ограничителю попыток входа)
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
