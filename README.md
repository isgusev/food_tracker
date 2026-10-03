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
   > ⚠️ Требуется **Python 3.12 или 3.13**. Python 3.9 не поддерживается (streamlit>=1.36),
> а Python 3.14 пока не имеет готовых бинарных пакетов pydantic-core/sqlalchemy —
> установка завершится ошибкой сборки из исходников.

```bash
   python3.12 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. PostgreSQL (docker): `docker compose up -d db`
3. Конфигурация: скопируйте `.env.example` → `.env`, укажите `POSTGRES_*` и **свой** `SECRET_KEY`.
4. Миграции (initial-ревизия уже в репозитории, autogenerate не нужен):
   ```bash
   alembic upgrade head
   ```
5. Демо-данные (при запущенном API): `python -m scripts.seed`
   (доступ: `demo / demo-pass-123`)
6. Запуск API: `uvicorn app.main:app --reload` (docs: http://localhost:8000/docs)
7. UI: `streamlit run ui_app.py` (откроется на http://localhost:8501)

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
