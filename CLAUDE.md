# ЕлиГуси (food_tracker) — контекст для Claude

Семейный планировщик питания: план на неделю для всей семьи → список покупок →
запасы дома → готовка/еда → личные КБЖУ каждого и деньги. Владелец — Иван
(isgusev), общение на русском, коммиты и UI — на русском.

**Бизнес-логика целиком** (как работает каждая часть, правила учёта):
документ «Food Tracker — бизнес-логика» — https://claude.ai/code/artifact/14483a43-200e-4562-a6f2-d14ba60c5c22
(Claude Docs; после изменений поведения — обновлять его раздел и «Историю изменений»).
История решений и дорожная карта — `docs/REVIEW.md`.

## Стек и структура

- Backend: FastAPI + SQLAlchemy 2.0 async + PostgreSQL 16 (asyncpg), Alembic, Pydantic v2, JWT.
  Слои: `app/models` → `app/repositories` (только SQL) → `app/services` (вся логика) →
  `app/api/v1/endpoints` (тонкие роутеры). Доменные ошибки → HTTP в `app/api/error_handlers.py`.
- Frontend: `web/` — Vue 3 **без сборки** (ESM из `web/vendor/`, Node на машине нет),
  раздаётся самим API на `/app/` (`Cache-Control: no-cache`). Экраны — `web/js/views/*.js`,
  общее состояние — `web/js/store.js`. PWA: `web/sw.js` (network-first), `manifest.webmanifest`.
- Сканер штрихкодов: BarcodeDetector, иначе `web/vendor/zxing.min.js` (для iPhone).

## Предметная модель (кратко)

- **Семья** (`Household`) — всё общее: рецепты, кастрюли, план, запасы, списки, бюджет.
  `HouseholdMember` — человек (с аккаунтом или без), цели КБЖУ. Каждый запрос скоупится
  по `CurrentMemberDep.household_id`.
- **План**: `MealItem` (дата, приём пищи, рецепт ИЛИ готовый продукт, кастрюля) +
  `MealPortion` (член семьи или гость=NULL, вес, `is_eaten`, `eaten_from_pot_id`).
- **Кастрюля** (`RecipeCookingLog`) резервирует несъеденные порции привязанных блюд;
  привязка с сегодняшнего дня по вместимости, освобождение поздних блюд при убывании.
- **Запасы** сверяются по ТОВАРУ = `Product.search_name` (без бренда); партии `StockLot`,
  каждое изменение — `StockMovement` (отмены возвращают в те же партии). Готовка списывает
  состав кастрюли, «съел» — готовый продукт. «Базовые» товары не учитываются.
- **Покупки** = потребность периода − (запасы − съедим до начала периода); общий
  `ShoppingList` (один активный на семью), «куплено» сразу создаёт партию.
- **Финансы** — из цен партий (`app/services/finance.py`).
- **Регистрация** только по одноразовым приглашениям (`RegistrationInvite`), первый
  пользователь — по `FIRST_INVITE_CODE`.

## Команды

```bash
.venv/bin/python -m pytest -q              # 70 тестов, SQLite in-memory (REGISTRATION_MODE=open в conftest)
.venv/bin/alembic upgrade head             # миграции (только PostgreSQL; 0001…0011)
.venv/bin/alembic check                    # модели == схема — проверять после новой миграции
.venv/bin/uvicorn app.main:app --reload    # http://localhost:8000/app/
.venv/bin/python -m scripts.seed           # демо-данные (локально нужен REGISTRATION_MODE=open)
.venv/bin/python -m scripts.invite         # код приглашения в обход UI
```
Миграции проверять на временном Postgres в Docker (upgrade / check / downgrade -1 / upgrade),
не трогая основную локальную базу пользователя (`food_tracker_db`, порт 5433).

## Ветки, деплой, CI

- `develop` → тестовый стенд Amvera (`food-tracker-test`), автодеплой на push.
- `main` → боевой стенд (`food-tracker`), деплой после успешного CI. В `main` — только
  после проверки на тесте (PR `develop` → `main`) или по явной просьбе Ивана.
- Работа — в feature-ветках от `develop`. CI: `.github/workflows/ci.yml` (pytest + цикл миграций).
- Хостинг: `Dockerfile`, `amvera.yml` (порт 8000), `scripts/start.sh` (wait_db → alembic →
  uvicorn), инструкция `docs/DEPLOY_AMVERA.md`. Push в GitHub работает (токен в связке ключей).

## Грабли, на которые уже наступали

- `Decimal // x` округляет к нулю — потолок через `ROUND_CEILING` (`app/domain.py`).
- SQL `LOWER()/ILIKE` не работает с кириллицей в SQLite — сравнивать в Python.
- Остатки `Numeric(…,1)` — количества `quantize()` ДО сравнения, иначе ложные «недостачи».
- Async SQLAlchemy: не трогать незагруженные связи (MissingGreenlet), не делать `expire_all`.
- Amvera сама задаёт `PORT` — порт в `start.sh` фиксирован 8000. Пароль БД экранируется в URL,
  `%` удваивается для alembic. `POSTGRES_PORT` по умолчанию 5433 (локальный) — на хостинге задавать.
- Встроенный браузер Claude: service worker не регистрируется, браузер кэширует JS —
  при проверке делать `fetch(файл, {cache:'reload'})` и перезагрузку.
- Тесты с датами — относительно `date.today()` (`day()` в `tests/test_api.py`).
- Необратимые локальные действия (удаление веток, stash, `docker stop` чужих контейнеров)
  требуют подтверждения Ивана.

## Как работать с Иваном

- Делать этапами: ветка → тесты → проверка в браузере → коммит → (по договорённости) слияние.
- Крупные решения кратко согласовывать; мелочи — решать самому и сообщать.
- Обновлять документ бизнес-логики и `docs/REVIEW.md` вместе с изменением поведения.
