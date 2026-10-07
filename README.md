# Food Tracker

Трекер питания: справочник продуктов (с версиями КБЖУ), рецепты/готовки, дневник питания.
Backend: FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL. UI: Vue 3 (`web/`, без сборки),
раздаётся самим API на http://localhost:8000/app/.

**Семья:** рецепты, холодильник, план и список покупок общие для семьи; у каждого
члена семьи (в том числе без аккаунта — ребёнок) свои порции и цели КБЖУ.
Второй взрослый вступает в семью по коду приглашения (раздел «Семья» в интерфейсе).

Разбор возможностей и план развития — [docs/REVIEW.md](docs/REVIEW.md).
Доступ на push в GitHub — [docs/GITHUB_ACCESS.md](docs/GITHUB_ACCESS.md).
Развёртывание на Amvera (тестовый и боевой стенды) — [docs/DEPLOY_AMVERA.md](docs/DEPLOY_AMVERA.md).

## Структура

```
app/
  core/          # конфигурация (pydantic-settings), безопасность (JWT, хэширование), исключения
  models/        # ORM-модели (по доменам: user, household, product, recipe, plan)
  schemas/       # Pydantic-схемы запросов/ответов
  db/            # engine/session (async), Base
  repositories/  # слой доступа к данным (только SQL/ORM)
  services/      # бизнес-логика (транзакции, доменные инварианты)
  api/           # deps (DI), error_handlers, v1/endpoints — тонкие роутеры
tests/           # pytest: доменные тесты + фикстуры для интеграционных (in-memory БД)
alembic/         # миграции схемы (versions/ — сгенерированные ревизии)
web/             # веб-интерфейс: index.html, styles.css, js/ (Vue 3 ESM, vendor/ — сама библиотека)
```

## Локальный запуск

1. Зависимости:
   > ⚠️ Требуется **Python 3.12 или 3.13** (так же проверяет CI). Python 3.14 пока не имеет
> готовых бинарных пакетов pydantic-core/sqlalchemy — установка завершится ошибкой сборки.

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
   (доступ: `demo / demo-pass-123`; создаётся семья с ребёнком «Маша» и ужином на сегодня)
6. Запуск: `uvicorn app.main:app --reload`
   - интерфейс: http://localhost:8000/app/ (корень `/` перенаправляет туда)
   - API docs: http://localhost:8000/docs

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

## Веб-интерфейс (`web/`)

Vue 3 подключён как ES-модуль из `web/vendor/` — без Node, npm и сборки: правите файл,
обновляете страницу. Структура:

```
web/js/api.js          # fetch + JWT (localStorage), разбор ошибок FastAPI
web/js/store.js        # общие справочники (продукты, рецепты), индексы, тосты
web/js/components.js   # Modal, Picker (поиск-выбор), Macros, IngredientsEditor
web/js/views/*.js      # экраны: planner (неделя/день), shopping, fridge, recipes, catalog, misc
```

Обновить Vue: скачать `https://cdn.jsdelivr.net/npm/vue@<версия>/dist/vue.esm-browser.prod.js`
в `web/vendor/`.
