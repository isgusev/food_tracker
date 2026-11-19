# Образ для хостинга (Amvera или любой Docker): API + веб-интерфейс одним процессом.

# Новый интерфейс (frontend/, Vite + TS) — собирается отдельной стадией, в образ попадает только dist
FROM node:22-slim AS web-next
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY web ./web
COPY --from=web-next /frontend/dist ./frontend/dist
COPY scripts ./scripts

# Переменные окружения (БД, SECRET_KEY…) задаются на хостинге, при сборке их нет
EXPOSE 8000
CMD ["sh", "scripts/start.sh"]
