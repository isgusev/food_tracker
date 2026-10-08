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
- Поиск продукта: `web/js/product-finder.js` — `ProductFinder` (план: справочник → штрихкод/📷 →
  Open Food Facts, выбранное из OFF = «черновик», сохраняется `saveDraft` при добавлении в план),
  `OffSearchModal` (форма «Новый продукт»), `OffDraftCard`. Общие компоненты — `web/js/components.js`
  (`Picker` с двухстрочными пунктами, `VariantPicker`, `KbjuInputs`, `BarcodeScanner`).
- Open Food Facts на сервере: `app/services/barcode.py` — по штрихкоду (`api/v2/product`) и по названию
  (`cgi/search.pl`, запасной `search.openfoodfacts.org`, кэш в памяти 10 мин — лимит OFF ~10 поисков/мин).
- Расчёт целей КБЖУ: `app/services/nutrition.py` (МР 2.3.1.0253-21: Миффлин–Сан Жеор × КФА;
  снижение −15 %, набор +10 %, белок 1,6 г/кг) → `POST /household/targets/calc`.

## Предметная модель (кратко)

- **Семья** (`Household`) — всё общее: рецепты, кастрюли, план, запасы, списки, бюджет.
  `HouseholdMember` — человек (с аккаунтом или без), цели КБЖУ и параметры для их расчёта
  (пол, год рождения, рост, вес, активность, цель). Каждый запрос скоупится
  по `CurrentMemberDep.household_id`.
- **План**: `MealItem` (дата, приём пищи, рецепт ИЛИ готовый продукт, кастрюля) +
  `MealPortion` (член семьи или гость=NULL, вес, `is_eaten`, `eaten_from_pot_id`).
- **Кастрюля** (`RecipeCookingLog`) резервирует несъеденные порции привязанных блюд;
  привязка с сегодняшнего дня по вместимости, освобождение поздних блюд при убывании.
- **Запасы** сверяются по ТОВАРУ = `Product.search_name` (без бренда); партии `StockLot`,
  каждое изменение — `StockMovement` (отмены возвращают в те же партии). Готовка списывает
  состав кастрюли, «съел» — готовый продукт. «Базовые» товары не учитываются.
- **Справочник** общий для всех семей: продукт = название + бренд, `barcode` (уникален),
  производители с версиями КБЖУ, упаковки `ProductPackage` в единице товара (г/мл/шт).
  `POST /products/with-category` с `reuse_existing` и `package_amount/unit` — сохранение из OFF без дублей.
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
- Регэкспы с `\d` и другими `\`-escape внутри шаблонов Vue (`template: \`…\``) ломаются —
  JS-литерал съедает обратный слэш. Проверки выносить в `computed`/функции в `setup`.
- `preview_start` по `.claude/launch.json` не может запустить сервер (нет доступа к папке проекта) —
  uvicorn запускать через Bash в фоне на временной базе (Docker, порт 5439) и открывать
  `preview_start` с `url` http://localhost:8001/app/; демо-данные — `scripts.seed --url … --user … --password …`.
- `gh` на машине нет — статус CI и деплоя смотреть в GitHub Actions / панели Amvera (сказать Ивану).
- Тесты с датами — относительно `date.today()` (`day()` в `tests/test_api.py`).
- Необратимые локальные действия (удаление веток, stash, `docker stop` чужих контейнеров)
  требуют подтверждения Ивана.

## Как работать с Иваном

- Делать этапами: ветка → тесты → проверка в браузере → коммит → (по договорённости) слияние.
- Крупные решения кратко согласовывать; мелочи — решать самому и сообщать.
- **Документация — часть каждого изменения, без напоминаний**, в том же коммите/сессии:
  - документ бизнес-логики: раздел изменившейся части + строка в «Истории изменений»;
  - `docs/REVIEW.md`: что сделано на этапе / дорожная карта;
  - этот `CLAUDE.md`: новые модули, эндпоинты, модели, миграции, счётчик тестов, команды и новые грабли.
  Перед коммитом сверить: всё ли новое отражено в трёх местах.
