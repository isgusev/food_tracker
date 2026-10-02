# Food Tracker

Трекер питания: справочник продуктов (с версиями КБЖУ), рецепты/готовки, дневник питания.
Backend: FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL. UI: Streamlit (`ui/`).

## Структура

```
app/
  core/          # конфигурация (pydantic-settings), безопасность (JWT, хэширование), исключения
  models/        # ORM-модели (по доменам: user, product, recipe, diary)
  schemas/       # Pydantic-схемы запросов/ответов
  db/            # engine/session (async), Base
  repositories/  # слой доступа к данным (только SQL/ORM)
  services/      # бизнес-логика (транзакции, доменные инварианты)
  api/           # deps (DI), error_handlers, v1/endpoints — тонкие роутеры
tests/           # pytest: доменные тесты + фикстуры для интеграционных (in-memory БД)
alembic/         # миграции схемы (versions/ — сгенерированные ревизии)
ui/              # Streamlit-приложение
```

## Локальный запуск

1. Зависимости:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. PostgreSQL (docker): `docker compose up -d db`
3. Конфигурация: скопируйте `.env.example` → `.env`, укажите `POSTGRES_*` и **свой** `SECRET_KEY`.
4. Миграции (первый запуск — сгенерировать initial-ревизию):
   ```bash
   alembic revision --autogenerate -m "initial schema"
   alembic upgrade head
   ```
5. Запуск API: `uvicorn app.main:app --reload` (docs: http://localhost:8000/docs)
6. UI: `streamlit run ui/app.py`

## Тесты

```bash
pip install pytest pytest-asyncio httpx aiosqlite   # уже в requirements.txt
pytest            # testpaths=tests указан в pytest.ini
```

## Миграции (Alembic)

- `alembic current` — какая ревизия применена в БД;
- после изменения моделей: `alembic revision --autogenerate -m "описание"`;
- применить: `alembic upgrade head`; откатить шаг: `alembic downgrade -1`.

Команды выполняются из корня проекта (рядом с `alembic.ini`). URL БД берётся
из приложения (`app.core.config`), а не из `alembic.ini` — настраивать `.env` достаточно.
