# Аудит фронтенда `web/` — чек-лист переноса на Vite + Vue + TS (`/next/`)

Источник: текущий код `web/js/**` (Vue 3 без сборки). Документ — контракт переноса: каждое действие пользователя
и каждый запрос к API должны появиться в новом приложении (или быть сознательно вычеркнуты из раздела 4).
Пути API — относительно `/api/v1`. `⚠️` — выглядит неиспользуемым, дублирующимся или непоследовательным.

Обозначения тел запросов: `{a, b?}` — `b` необязателен; `a|null` — допускается `null`.

---

## 1. Оболочка, навигация, состояние

### 1.1 Маршруты (hash-роутер, `app.js` → `parseHash`)

Формат: `#/<name>/<param>?<query>`. Пустой hash → `plan`. Экран перерисовывается по ключу `name/param?query`
(кроме `shopping` — ключ фиксированный `'shopping'`, ⚠️ смена `?start/end` при открытом экране не пересоздаёт его).
При смене hash — `window.scrollTo(0,0)`.

| Маршрут | Экран | Параметры |
|---|---|---|
| `#/plan` | `PlannerView` | `?week=YYYY-MM-DD` (любой день недели → понедельник) |
| `#/day/<YYYY-MM-DD>` | `DayView` | дата в `param` |
| `#/shopping` | `ShoppingView` | `?start=&end=` — сразу сформировать список за период |
| `#/fridge` | `FridgeView` (вкладки Готовое / Продукты / Архив — локальное состояние, в URL нет) | — |
| `#/recipes` | `RecipesView` | — |
| `#/catalog` | `CatalogView` (вкладки Продукты / Товары, вкладка — в `ft.catalogTab`) | — |
| `#/money` | `MoneyView` | — |
| `#/family` и `#/profile` | `FamilyView` (`profile` — ⚠️ старый алиас) | — |
| `#/register?code=XXXX` | обрабатывает `LoginView` (только когда не вошли) | `code` — код приглашения |
| прочее | «Страница не найдена. К плану» | — |

⚠️ `#/register?code=…`, открытая уже вошедшим пользователем, даёт «Страница не найдена».

### 1.2 Меню

Один массив `NAV` для боковой панели (desktop) и таб-бара (mobile):
📅 План (`plan`, активен и на `day`) · 🛒 Покупки · 🧊 Холодильник (в таб-баре «Холод.») · 🍲 Рецепты ·
📦 Продукты (`catalog`) · 💰 Деньги · 👪 Семья. В подвале боковой панели — `username` и название семьи.
Иконка-логотип `icons/icon.svg`.

### 1.3 Авторизация

- Токен JWT — `localStorage['ft.token']` (сырой строкой, не JSON). Заголовок `Authorization: Bearer`.
- Запуск (`bootstrap`): нет токена → `LoginView`. Есть → `GET /auth/me` → `state.user`, затем `loadHousehold()`.
  Ошибка 401 → токен стирается, вход; любая другая (сеть) → экран «Нет связи с сервером» с кнопкой «Повторить»
  (только если `state.user` не получен; с service worker `/auth/me` и `/household` отдаются из кэша офлайн).
- Любой ответ 401 при наличии токена (`api.js`) → `auth.clear()` + `onUnauthorized` → `state.user = null` → экран входа.
- Вход: `POST /auth/login` **form-urlencoded** `{identifier, password}` → `{access_token}`.
- Регистрация: `POST /auth/register {username, email, password, invite_code|null}`, затем автоматически вход.
- Выход (кнопка в «Семье»): только локально — `auth.clear()`, сброс `user, household, products, recipes, loaded`.
  ⚠️ Не сбрасываются `productCategories`, `recipeCategories`, `viewMemberId`, очередь `ft.shopQueue`; запроса на сервер нет.
- Ошибки API (`ApiError{status, message}`): сеть → `status 0`, «Нет связи с сервером…»; 204 → `null`;
  422 pydantic → `loc: msg; …` (без `body.` и «Value error, »); `detail` объектом → `detail.message`.

### 1.4 Тема

`ft.theme` = `auto | light | dark`. Применяется до монтирования: `data-theme` на `<html>` (для `auto` атрибута нет).
Переключатель — «Семья → Оформление». `index.html`: `theme-color` для светлой/тёмной схемы.

### 1.5 Глобальное состояние (`store.js`)

| Поле | Что | Когда грузится / перезагружается |
|---|---|---|
| `user` | `GET /auth/me` | bootstrap |
| `household` `{id, name, invite_code, me_member_id, portion_tolerance, members[]}` | `GET /household` | bootstrap; после `PUT /finance/budget`, `POST /household/join`; ответы `PATCH /household*`, `POST /household/members`, `POST /household/invite-code` подменяют его целиком |
| `viewMemberId` | чьи КБЖУ показывать в плане | из `ft.viewMember.<userId>`, если член ещё в семье, иначе `me_member_id` |
| `products`, `productCategories` | `GET /products/?limit=2000`, `GET /products/categories` | `loadProducts()`: лениво через `ensureCatalog()` и после любых правок справочника |
| `recipes`, `recipeCategories` | `GET /recipes/?limit=500`, `GET /recipes/categories` | `loadRecipes()`: лениво и после сохранения/удаления рецепта, после вступления в семью |
| `toasts` | уведомления | `toast(text, kind='info', ms=3500)`; `toastError(e)` — `error`, 6000 мс |
| `loaded` | флаги «уже загружено» | `ensureCatalog()` грузит то, что ещё не загружено |

Производные индексы: `categoryName`, `recipeCategoryName`, `recipeById`, `members`, `activeMembers` (`is_active`),
`memberById`, `viewMember`, `variantIndex` (variant_id → `{product, manufacturer, variant, name, sub (бренд · производитель,
если отличается), subFull (+ упаковки или «100 г»), label, category, active, kbjuMissing, version, КБЖУ}`),
`activeVariants` (только активные версии, сорт. категория → название), `variantLabel(id)`.
Цели: `targetsOf(member)` (незаданные — `null`), `targetsForMeters` (незаданные → ориентир 2000 / 100 / 70 / 230),
`hasTargets`.

`useAction({inline, done})` → `{busy, error, run(fn, msg)}`: выполняет, вызывает `done(res)`, тост `msg`;
ошибка — в `error` (inline) или тостом.

### 1.6 Опрос сервера

- «Покупки»: `GET /shopping-lists/active` каждые 15 с (`POLL_MS`), если вкладка видима и не открыт `BoughtModal`;
  плюс при `visibilitychange` (и заодно `GET /receipts`), при событии `online` (сначала сброс офлайн-очереди).
- Окно чека: «ждущий» чек — `GET /receipts/{id}` каждые 4 с первую минуту, затем каждые 15 с до 3 минут, с обратным отсчётом.
- Больше опроса нигде нет.

### 1.7 PWA и офлайн

- `manifest.webmanifest`: `start_url /app/#/plan`, `scope /app/`, standalone, ярлыки «Покупки», «План».
- `sw.js` (`CACHE = "ft-v7"`): при установке кэширует оболочку (`SHELL` — полный список модулей; полноту проверяет
  `scripts/check_web.sh`), `skipWaiting` + `clients.claim`, старые кэши удаляются. Только `GET`; стратегия
  «сначала сеть», офлайн — из кэша. Кэшируется всё под `/app/` (с `ignoreSearch`) и API только из списка:
  `/shopping-lists/active`, `/auth/me`, `/household`, `/finance/prices`.
- Офлайн-очередь отметок «куплено» (`ShoppingView`): при сетевой ошибке (`status 0`) отметка ставится локально,
  в `ft.shopQueue` пишется `{id, kind: 'check'|'uncheck'}` (одна запись на строку, последняя побеждает), тост
  «Нет сети — отметка отправится…». Сброс — перед каждым `refresh()` и по `online`: последовательные
  `POST /shopping-lists/lines/{id}/{kind}`; не сетевые ошибки молча выбрасываются; если всё ушло — тост
  «Отметки, сделанные без сети, отправлены». В шапке списка — бейдж «не отправлено: N».
- SW регистрируется только в безопасном контексте (ошибка регистрации глушится).

### 1.8 Ключи `localStorage` (все JSON, кроме `ft.token`)

| Ключ | Что хранит | Где |
|---|---|---|
| `ft.token` | JWT (строка) | `api.js` |
| `ft.theme` | `auto/light/dark` | `app.js`, `FamilyView` |
| `ft.viewMember.<userId>` | id члена семьи, чьи КБЖУ показывать | `store.js` |
| `ft.week` | последняя открытая неделя плана | `PlannerView` |
| `ft.portions.r.<recipeId>` / `ft.portions.v.<variantId>` | «как в прошлый раз»: `{members: {memberId: г}, guests, guestWeight, mode, pkgIdx, pkgCount, pkgSplit}` | `AddItemModal` |
| `ft.none` | ⚠️ не пишется никогда — заглушка-ключ для черновика продукта (всегда пусто) | `AddItemModal.productDefaults` |
| `ft.lastProductCategory` | последняя категория нового продукта | `product-finder.js`, `receipts.js` |
| `ft.shopQueue` | офлайн-очередь отметок | `ShoppingView` |
| `ft.regularOpen` | раскрыт ли блок «Обычно берём» | `RegularBlock` |
| `ft.catalogTab` | `products/items` | `CatalogView` |
| `ft.itemSuggestionsHidden` | скрытые предложения объединить товары (id группы = отсортированные ключи через `|`) | `ItemsPanel` |

---

## 2. Экраны

### 2.1 План — `PlannerView` (`#/plan`)

**Показывает.** Неделю пн–вс (`?week` → `ft.week` → сегодня); 7 карточек дней × 4 приёма пищи (`MEALS`: завтрак,
обед, ужин, перекус). Сегодня/прошедшие дни подсвечены. У дня: число, день недели, «сегодня» или месяц (ссылка на
`#/day/<дата>`), полоса ккал выбранного члена (красная при > 110 % цели), строка «ккал · Б · Ж · У · съедено N».
Статистика недели: переключатель члена семьи (`MemberSwitch`, если активных > 1), «Блюд», «Приготовить» (уникальные
рецепты с `state='to_cook'` среди не съеденных), «Купить готовым» (`kind='product'`), средние ккал/день выбранного
(«(цель N)», если цели заданы).
Карточка блюда (`.entry`): полоса состояния `st-product | st-to_cook | st-in_fridge`, классы `fact` (всё съедено),
`auto` (предложение, «карандашом»), `pinned`; иконка (`✓` всё съедено, `🛍` продукт, `◐` в холодильнике, `○`);
имя + 📌; порция выбранного «г · ккал ✓» или «без <имя>»; «ещё N»; предупреждение бейджа (`itemBadge`, если `warn`);
`auto_reason` для auto.
Панель черновика, если есть `origin='auto'`: «Черновик: N предложений», «Убрать» (если есть «свободные» —
без 📌, без кастрюли, без съеденного), «✓ Принять всё».

**Действия → API.**

| Действие | Запрос |
|---|---|
| загрузка недели | `ensureCatalog()`, `GET /plan?start_date&end_date` |
| ‹ / › / «Текущая» (видна, если неделя не текущая) | смена недели, запись `ft.week`, перезагрузка |
| ✨ Предложить неделю (выкл., если неделя в прошлом) | `POST /plan/autofill {start: max(пн, сегодня), end: вс}` → тост «Предложено блюд: N (прежних предложений заменено: M)…» или «Нечего предложить…» |
| ✨ у дня (только `d >= сегодня`) | `POST /plan/autofill {start: d, end: d}` |
| 🧊 Только остатки | `POST /plan/autofill {start, end, cook: false}` |
| ⧉ Прошлая неделя | `GET /plan` за прошлую неделю; пусто → тост; `confirm` («…уже есть N блюд — они останутся»); на каждое блюдо `POST /plan {date_day+7, meal_type, recipe_id | variant_id+exact, portions[{member_id, weight_g}]}` (пропуск, если нет ни рецепта, ни продукта) |
| Шаблоны | `TemplatesModal` |
| 🛒 Покупки на неделю | ссылка `#/shopping?start=<сегодня, если неделя текущая, иначе пн>&end=<вс>` |
| + у приёма пищи | `AddItemModal {date, meal, days: неделя}` |
| клик по блюду | `ItemModal (план)` |
| перетаскивание блюда (HTML5 drag&drop, только мышь) на другую ячейку | `PATCH /plan/{id} {date_day, meal_type}` (та же ячейка — ничего) |
| ✓ у предложения | `POST /plan/{id}/accept` |
| 📌 | `PATCH /plan/{id} {pinned: !pinned}`, тост «Закреплено — перегенерация не тронет» / «Откреплено» |
| 🔄 (только рецепт без кастрюли и без съеденного) | `POST /plan/{id}/alternative` |
| ✕ у предложения | `DELETE /plan/{id}` (без подтверждения) |
| ✓ Принять всё | `POST /plan/accept {start: пн, end: вс}` |
| Убрать (черновик) | `confirm`, затем `DELETE /plan/{id}` на каждое «свободное» ⚠️ N запросов, отдельного bulk-эндпоинта нет |

**Правила.** После любого действия — полная перезагрузка недели. Поля блюда, на которые опирается UI:
`id, date_day, meal_type, kind (recipe|product), state (to_cook|in_fridge), name, recipe_id, variant_id, exact,
origin, pinned, auto_reason, cooking_log_id, fridge_pot_id, fridge_enough, fridge_available_g, fridge_reserved_g,
portions[{id, member_id|null, member_name, weight_g, calories, proteins, fats, carbs, is_eaten, eaten_from_pot_id}]`.
`itemBadge`: продукт → «Готовый продукт»; всё съедено → «Съедено»; `in_fridge` → «Из холодильника» / «В холодильнике
не хватает» (`fridge_enough=false`); есть `fridge_pot_id` и хватает → «Есть в холодильнике · свободно X»
(available − reserved); не хватает → «Надо приготовить · в кастрюле не хватит»; иначе «Надо приготовить».
⚠️ Копирование прошлой недели и «Убрать» — циклы одиночных запросов, без отката при ошибке на середине.

#### `TemplatesModal`
- Загрузка `GET /plan/templates` → `[{id, name, items_count, meals_per_day[7]}]`, строка «пн N, вт N…».
- «Сохранить эту неделю» (нужно имя; Enter): `POST /plan/templates {name, week_start}`.
- «Применить»: `POST /plan/templates/{id}/apply {week_start}` → `{created, skipped}`, тост «Добавлено блюд: N, пропущено M
  (рецепт удалён или едок скрыт)», окно закрывается, неделя перезагружается. Применение добавляет, не заменяет.
- ✕: `confirm` → `DELETE /plan/templates/{id}`.

#### `AddItemModal` (из плана и дня)
**Показывает.** Переключатель «🍲 Блюдо / 🛍️ Готовый продукт»; выбор блюда (`Picker`, группы — категории рецептов,
справа «ккал/100 г» + Б/Ж/У, подсказка «Стандартная порция ≈ N г» = выход / порций); для продукта — `ProductFinder`
(`kbjuPrompt`) + `OffDraftCard` для черновика + чекбокс «🎯 Именно этот вариант»; режим «По упаковке / Вес вручную»
(если есть упаковки): N × упаковка, «каждому / на всех»; строки активных членов семьи (чекбокс, вес 1–2000, ккал
справа); гости 0–10 × вес; «всего X»; подсказка кастрюли; приём пищи; дни недели (мультивыбор, минимум один).

**Правила по умолчанию (порции).**
1. Старт: все активные члены отмечены, 250 г.
2. Выбран рецепт → `ft.portions.r.<id>`: если есть — отмечены только те, кто был, их веса, гости, вес гостя;
   иначе вес = стандартная порция (или 250) и затем `GET /plan/typical-portions {meal_type, recipe_id}` →
   `[{member_id, weight_g}]` подменяет веса (ответ отбрасывается, если рецепт уже сменили).
   ⚠️ Типичные порции берутся по приёму пищи на момент выбора рецепта; смена приёма их не пересчитывает;
   для готовых продуктов не запрашиваются.
3. Выбран продукт → `ft.portions.v.<variantId>` (или ничего для черновика), запасной вес 100 г; восстанавливает
   режим/упаковку/количество/деление; режим «по упаковке» по умолчанию, если упаковки есть и в памяти не «manual».
4. Упаковки: у продукта — все `packages` → граммы (`pcs` × `piece_weight_g`; ≤ 0 — отбрасываются); у черновика —
   одна, если `package_amount > 0` и единица не `pcs`. «По упаковке»: граммы × N, «каждому» — каждому столько,
   «на всех» — делится на число едоков (отмеченные + гости), округление до 0,1; поля веса блокируются.
5. Подсказка кастрюли (только рецепт и всего > 0): `GET /plan/pot-status/{recipeId}?portion_g=всего` →
   `{has_active_pot, available_g, planned_g}` → «осталось X, запланировано Y. Свободного хватает — возьмём из кастрюли»
   (info) или «Свободно только Z — блюдо попадёт в покупки как "надо приготовить"» (warn).

**Сохранение.** Ошибки inline: «Выберите блюдо», «Выберите продукт», «Сначала внесите КБЖУ продукта — поля выше»
(`kbjuMissing`), `draftError(draft)`, «Отметьте, кто ест». Черновик → `saveDraft(draft)` (reuse) → `activeVariantOf`
(нет версии — ошибка). Затем на каждую выбранную дату по возрастанию `POST /plan {date_day, meal_type,
portions[{member_id|null, weight_g}], recipe_id | variant_id + exact}` (порции с весом 0 и неотмеченные не уходят).
Запись «как в прошлый раз» под ключом рецепта/варианта. Тост «Добавлено в план» / «Добавлено в N дн.».

#### `ItemModal` (карточка блюда плана)
**Показывает.** Бейдж `itemBadge`, приём · день, «в кастрюле X»; для auto — плашка «Предложено планировщиком: <причина>»
с 📌 / 🔄 Другое (условие как в плане) / ✓ Принять; таблица порций (кто, вес, ккал, статус «✓ съел · из холодильника»
или «в плане»).

| Действие | Запрос |
|---|---|
| ✓ Съел (вес — из поля; Enter в поле у несъеденной) | `POST /plan/portions/{id}/eat {weight_g}` |
| ↺ (отменить съедено) | `POST /plan/portions/{id}/uneat` |
| «без холодильника» (съедено из кастрюли) | `POST /plan/portions/{id}/detach` |
| Сохранить (вес изменён; Enter у съеденной) | `PATCH /plan/portions/{id} {weight_g}` |
| ✕ порции (последняя — `confirm` «блюдо будет удалено», затем окно закрывается) | `DELETE /plan/portions/{id}` |
| + Добавить едока (недостающие активные члены или «Гость») | `POST /plan/{id}/portions {member_id|null, weight_g}` (вес по умолчанию — вес первой порции или 200) |
| Перенести (в `<details>`: дата + приём) | `PATCH /plan/{id} {date_day, meal_type}` |
| ✓ Все поели (если есть несъеденные) | `POST /plan/{id}/eat` ⚠️ веса из полей не передаются |
| Удалить блюдо (`confirm`, «Съеденное вернётся в кастрюлю», если ели из кастрюли) | `DELETE /plan/{id}` |
| 📌 / 🔄 / ✓ Принять | `PATCH /plan/{id} {pinned}` / `POST /plan/{id}/alternative` / `POST /plan/{id}/accept` |

Ответ действия (обновлённое блюдо) подменяет карточку; родитель получает `changed` и перезагружает неделю/день; закрытие
окна тоже перезагружает. Ошибки — inline.

### 2.2 День — `DayView` (`#/day/<дата>`)
- `ensureCatalog()`, `GET /plan?start_date=d&end_date=d`.
- Навигация: «‹ Неделя» (`#/plan?week=<пн>`), ‹ › по дням, бейдж «сегодня»; `MemberSwitch`.
- По 4 приёмам: «+ Добавить» → `AddItemModal {date, meal, days: неделя этого дня}`; блюда: иконка, имя, `itemBadge`,
  порция выбранного (вес, «✓ съел», `Macros`) или «<имя> это не ест», «Ещё: имя N г ✓, гость…». Клик → `ItemModal`.
- Боковая карточка «КБЖУ: <имя>»: `MacroMeters` (план+съеденное против цели; «цели не заданы — показан ориентир»),
  «Уже съедено», «Можно добавить ещё N ккал» / «Перебор на N ккал», «не хватает N г белка», ссылка «Цели членов семьи».

### 2.3 Покупки — `ShoppingView` (`#/shopping`)

**Показывает.** Кнопки «🧾 Чек» (primary и «· готов N», если есть расшифрованные неразобранные чеки),
«📋 Копировать», «Закрыть список». Период «С/По», «Сформировать список / Пересчитать», пресеты «До конца недели»,
«Следующая неделя», «3 дня». Строка: период · осталось / куплено · ≈ сумма ₽ (+ N без цены) · бейдж очереди;
«+ Внеплановая покупка»; `RegularBlock`; строки по категориям: чекбокс, название, бейджи «заканчивается» (staple),
«вне плана», «🎯 <бренд>» (exact) или «обычно <бренд>» (для extra — просто бренд), количество (`pkgText`: «N × упаковка»,
для 1 шт — «1 шт»; без упаковки — `needed`), «≈ N ₽», «📦 пачка?», ✕. Блок «Куплено — уже в запасах» с суммой,
у строки — количество · цена · «до дата», кнопка «Цена…» / «Изменить».

| Действие | Запрос / правило |
|---|---|
| открытие | `GET /shopping-lists/active` (период берётся из списка, если нет `?start`); `GET /finance/prices` → `{item_key: unit_price}`; `GET /receipts` (счётчик `status='done'`); `ensureCatalog()` в фоне |
| пришли с `?start&end`, а у активного другой период | автоматически `POST /shopping-lists {start_date, end_date}` |
| Сформировать / Пересчитать (конец < начала → тост-ошибка) | `POST /shopping-lists {start_date, end_date}`, тост «Список обновлён по плану и запасам» |
| пресеты | только меняют даты (rest: сегодня…вс, next: пн+7…вс+7, 3d: сегодня…+2) |
| чекбокс «купил» | `POST /shopping-lists/lines/{id}/check {}` (офлайн — в очередь) |
| снять «куплено» | `POST /shopping-lists/lines/{id}/uncheck {}` (офлайн — в очередь) |
| ✕ строки (без подтверждения) | `DELETE /shopping-lists/lines/{id}` |
| Цена… / Изменить | `BoughtModal` |
| 📦 пачка? (нет упаковки, не staple, единица не `pcs`) | `PackageModal` → после сохранения `POST /shopping-lists` за тот же период, тост «Упаковка сохранена — список пересчитан» |
| + Внеплановая покупка | `ExtraModal`, ответ — новый список, тост «Добавлено в список» |
| 📋 Копировать | в буфер: «Категория:\n☐ название — количество» (только некупленное) |
| Закрыть список | `confirm` (+ «У N покупок не указана цена…»), `POST /shopping-lists/{id}/close` |
| 🧾 Чек | `ReceiptModal`; после «applied» — `refresh()` + счётчик чеков |

Поля строки: `id, product_id, product_name, item_key, category_name, brand, unit, needed, package_amount,
package_count, is_checked, is_staple, is_extra, is_exact, bought_quantity, price, expires_on`; списка:
`id, start_date, end_date, updated_at, lines[]`. Оценка суммы = `unit_price × (package_amount × package_count | needed)`.

#### `BoughtModal`
Поля: «Купили, ед.» (`bought_quantity`), «Цена за всё, ₽» (пусто = null), «Годен до», «Какой бренд купили» — только если
не `is_exact` и у товара (`item_key`) > 1 продукта. `PATCH /shopping-lists/lines/{id} {quantity, price|null,
expires_on|null, product_id?}` (`product_id` — только если сменили). Ответ — список.

#### `PackageModal`
«Сейчас нужно X». `POST /products/{product_id}/packages {amount}` (≤ 0 — тост-ошибка), Enter сохраняет.

#### `ExtraModal` (внеплановая покупка)
`ProductFinder` (без `kbjuPrompt`) + `OffDraftCard kbjuOptional`. Упаковки — уникальные размеры всех продуктов того же
`item_key` (по возрастанию); у черновика — его `package_amount`. Режим «Упаковками» включается автоматически, если
упаковки есть. Ошибки: «Выберите продукт», `draftError(…, {kbjuOptional})`, «Укажите, сколько купить».
Черновик → `saveDraft` (reuse) → `POST /shopping-lists/{listId}/lines {product_id, quantity}`.
Подсказка: товар уже в списке — количество прибавится к строке (логика на сервере).
⚠️ Единица черновика берётся из `package_unit`, а не из единицы товара.

#### `RegularBlock` («Обычно берём»)
- `GET /shopping-list/regular {start_date, end_date}` (⚠️ путь в единственном числе, в отличие от `/shopping-lists/*`);
  перезапрашивается при смене `id / updated_at / числа строк` списка. Ответ `{items[{item_key, product_id, name,
  is_snack, always, weeks_bought, weeks, weekly, unit, to_buy, package_amount, package_count, est_price}],
  snacks{quota, spent, hidden}}`. Блок виден, если есть предложения или задана квота.
- Свёртка (`ft.regularOpen`); квота снеков: «N из M ₽», полоса, «Не предлагаем N — квота недели кончилась».
- Причина: «всегда берём» или «брали X из Y недель» · «Z в неделю».
- «+»: `POST /shopping-lists/{id}/lines {product_id, quantity: package_amount×package_count | to_buy}`;
  «+ Добавить всё» (если > 1) — то же последовательно; ✕: `PATCH /stock/items/{product_id} {regular: 'never'}`.

#### `ReceiptModal` (чек по QR, `receipts.js`)
**Экран выбора:** «📷 Сканировать QR чека» (`BarcodeScanner qr`) или строка из QR (≥ 10 символов, иначе «Отсканируйте
QR-код…»); «Недавние чеки» (`GET /receipts` → `{id, store_name, purchased_at, items_count, total, status}`; статусы:
ждём ФНС / проверить / ошибка / сохранён) — клик `GET /receipts/{id}`. При открытии ещё `GET /shopping-lists/active`
(только неотмеченные строки).
- Загрузка: `POST /receipts {qr}`. Статус `pending` → алерт + опрос (1.6) + «Проверить сейчас» (`GET /receipts/{id}`);
  `error` → текст ошибки; `applied` → «уже сохранён».
- **Разбор (`done`).** На строку чека: селект «— не учитывать» / строки списка (одна строка списка — одной строке чека,
  занятые выключены) / «Другой продукт из справочника…» (`Picker` по всем продуктам) / «Новый продукт — нет в справочнике…»
  (название, категория с datalist, «Похожие уже есть:» до 3 продуктов с нечёткостью ≥ 0,6 — клик берёт существующий);
  количество (пусто = «авто», отправляется только если правили) + единица; источник «запомнено / из списка · N % / похоже · N %».
- Начальный выбор (`rowFrom`): `suggestion.action='list'` и строка есть в списке → эта строка; иное не `skip` с
  `product_id` → продукт; иначе пропуск. Новое название (`cleanName`) — без размера, «вес», «,кг»; упаковка (`packOf`) —
  последний «N г/кг/мл/л» в названии, кроме весового товара (дробное количество, «вес», «, кг»).
- «Сохранить N покуп. · X ₽»: проверки («Выберите продукт для …», «Укажите название и категорию…»); новые →
  `POST /products/with-category {category_name, name, reuse_existing: true, package_amount|null, package_unit|null}`
  (без КБЖУ, запоминает категорию), `loadProducts()`; затем `POST /receipts/{id}/apply {lines[{index, action:
  'skip'|'list'|'extra', shopping_line_id?, product_id?, price: sum, quantity?}]}`, тост «Чек сохранён, покупок: N».
- «← Другой чек» — назад к выбору (перечитывает контекст). ⚠️ Ошибка при заведении части новых продуктов оставляет
  уже созданные (дублей не будет благодаря `reuse_existing`).

### 2.4 Холодильник — `FridgeView` (`#/fridge`)

Шапка: вкладки «Готовое (N)», «Продукты», «Архив» (⚠️ вкладка не запоминается, в отличие от `ft.catalogTab`),
«🍳 Приготовить» → `CookModal`.
Загрузка: `ensureCatalog()`, `GET /recipes/cooking-logs`, `GET /recipes/cooking-logs/archive?include_deleted=true`,
`GET /finance/pot-costs` → `{pot_id: {cost, complete}}`.

**Готовое.** Две группы: обычные и «❄️ Морозилка — заготовки» (`is_frozen`). Строка кастрюли: имя (рецепт из
справочника → `recipe_name` → «Рецепт #id» / «Рецепт удалён»), «осталось из выхода», полоса (остаток + запланированная
часть), дата готовки, «съесть/годно до <good_until>» (просрочено — цветом), ккал/100 г, себестоимость «N ₽» («+», если
не полная), «Свободно X · в планах Y» или «В планах на X больше, чем осталось». Клик → `PotModal`.
**Продукты** — `StockTab` (пересоздаётся после готовки/правки кастрюли через `stockKey`).
**Архив**: имя, «выброшено/доедено» (`is_discarded`), дата, вес, ккал, список `events[]` (строки с сервера).

#### `CookModal` (из «Холодильника» и из «Рецептов» с `recipeId`)
- Без `recipeId` — `Picker` рецептов (по алфавиту); выбор подставляет состав `template_ingredients` (`variant_id`,
  `weight_g`) и вес `estimated_cooked_weight`.
- `IngredientsEditor` (без 🎯), «Вес готового блюда, г».
- Нехватка: `GET /stock` → индекс по `item_key`; нужное суммируется по продуктам (граммы → единица товара);
  staple пропускаются; «не хватает», если есть < нужно × (1 − допуск семьи). Алерт «В запасах не хватает: … Готовить
  можно — товар пометится "уточнить остаток"».
  ⚠️ Ключ нужного — `product.name.toLowerCase()`, а запасов — `item_key`: после объединения/переименования товаров
  нехватка считается неверно; нужно `product.item_key`.
- «Приготовлено»: `resolveDraftIngredients`, хотя бы один ингредиент с весом,
  `POST /recipes/{id}/cook {total_cooked_weight, ingredients[{variant_id, weight_g}]}`, тост «Блюдо в холодильнике…».
  ⚠️ вес готового не проверяется (0 по умолчанию без рецепта). Из «Рецептов» после готовки — переход на `#/fridge`.

#### `PotModal`
| Действие | Запрос / правило |
|---|---|
| Сохранить остаток (0…выход) | `PATCH /recipes/cooking-logs/{id} {current_remaining_weight}`; тост зависит от допуска: ≥ план — «Остаток обновлён»; меньше, но в допуске — «Порции в плане уменьшены пропорционально»; иначе — «Планам, которым не хватит, — снова "надо приготовить"» |
| Изменить фактический состав… → «Пересчитать КБЖУ» | `resolveDraftIngredients`, `PUT /recipes/cooking-logs/{id}/ingredients {ingredients[{variant_id, weight_g}]}` |
| ❄️ Заморозить остаток | `POST /recipes/cooking-logs/{id}/freeze {}` (срок по умолчанию на сервере, +60 дн.) |
| Сохранить срок (у заготовки; дата ≥ сегодня, изменена) | `POST /recipes/cooking-logs/{id}/freeze {keeps_until}` |
| Достать из морозилки | `POST /recipes/cooking-logs/{id}/unfreeze` |
| 🗑 Выбросить остаток (`confirm`) | `POST /recipes/cooking-logs/{id}/discard` |
| Удалить… | `GET /recipes/cooking-logs/{id}/usage` → `{past_dates[], current_future_dates[]}`: есть прошлые — удалить нельзя (совет «Выбросить»); есть текущие/будущие — «Оставить в плане» (`remove_from_diary=false`) или «Удалить и их» (`true`); иначе «Удалить» → `DELETE /recipes/cooking-logs/{id}?remove_from_diary=` |

Показывает: дата, сырой → готовый вес, «съесть до», КБЖУ на 100 г, «Запланировано». Любое успешное действие закрывает окно
и перезагружает экран.

#### `StockTab` («Холодильник → Продукты»)
- `ensureCatalog()`, `GET /stock` → `[{item_key, product_id, name, category_name, unit, remaining, is_staple, is_low,
  needs_check, nearest_expiry, expired, regular, regular_qty, is_snack, lots[{id, product_id, quantity, remaining,
  expires_on, purchased_on, brand, source, price}]}]`.
- Поиск по названию (`matches`), группы по категориям; бейджи «базовый», «заканчивается», «учёт сбился»; «годен до»,
  «просрочено X»; остаток (кроме staple). Шапка: «+ Добавить» (`AddLotModal`), «Инвентаризация» (`QuickInventory`),
  счётчик «учёт сбился: N». Мутации запасов отвечают полным списком — он подменяет экран.

#### `AddLotModal`
- `Picker` по всем продуктам (справа — единица) + 📷: `GET /products/barcode/{code}`; `source='local'` → выбор, тост «Нашли»;
  иначе тост «Этого штрихкода нет в справочнике — добавьте продукт в "Продукты"».
- «Количеством»: `POST /stock/lots {product_id, quantity, price|null, expires_on|null}`.
- «По пачкам "Честный знак"»: `PacksEditor` + «Цена за все пачки» → `POST /stock/lots/packs {product_id, pack_amount,
  price|null, packs[{code|null, expires_on|null}]}`. Размер пачки по умолчанию — первая упаковка продукта.
  Сканирование кода без выбранного продукта выбирает продукт из кода.

#### `PacksEditor` (`marking.js`)
- «📷 Сканировать пачки» (`BarcodeScanner marks`, счётчик пачек) → на каждый код `POST /stock/marks/parse {code}` →
  `{gtin, serial, barcode, expires_on, product_id, product_name, already_registered}`.
  Правила: уже в запасах → ошибка; та же пачка (gtin+serial) в списке — игнор; код другого товара (штрихкод или product_id
  не совпадает) → ошибка; продукт не выбран → `emit product`; нет в справочнике → ошибка. Срок из кода — бейдж (не правится),
  иначе поле даты и тост «В коде нет срока годности».
- «+ Пачка без кода» (срок копируется с последней). Размер пачки — селект упаковок + поле. Сводка «N пач. · X», «2 × до 20 окт
  · 1 без срока»; ✕ пачки; «Пачек больше, чем осталось в партии» при `max`.

#### `SplitLotModal` («📦 Сроки» у партии)
`PacksEditor` с `max = lot.remaining`, размер по умолчанию — упаковка или весь остаток.
`POST /stock/lots/{lotId}/packs {pack_amount, packs[]}`, тост «Сроки по пачкам сохранены».

#### `ItemModal` (запасы; ⚠️ одноимённый с карточкой блюда плана)
- `GET /stock/items/{product_id}/history` → `[{id, created_at, reason, note, delta}]` (в `<details>`, причины —
  `REASON`: покупка / добавлено / инвентаризация / готовка / съедено / списано). Перечитывается после каждого действия.
- Партии по сроку (раньше — выше; без срока — в конце), просроченные цветом, «куплено · бренд · источник · цена»,
  «📦 Сроки» → `SplitLotModal`.
- «Уточнить остаток → Так и есть»: `POST /stock/items/{product_id}/inventory {quantity}`.
- «Списать»: `POST /stock/items/{product_id}/write-off {quantity, note|null}` (кнопка выкл. без количества).
- Флаги — `PATCH /stock/items/{product_id}`: `{is_staple}` («Сделать базовым / Учитывать остаток»), `{is_low}` (только у
  staple: «Заканчивается / Хватает»), `{regular: auto|always|never}`, `{regular_qty|null}` («В неделю», пусто — медиана),
  `{is_snack}`. Блок «Обычно берём» и остатки — только не у staple.
- ⚠️ Всё адресуется `product_id`, хотя учёт — по товару (`item_key`); сервер сам переходит к товару.

#### `QuickInventory`
Строки — все не staple: «Так и есть / Нет / Другое (число)». Сохранение — последовательно
`POST /stock/items/{product_id}/inventory {quantity}` для «Нет», «Другое» и для «Так и есть» у `needs_check`
(подтверждает записанное). Тост «Инвентаризация сохранена».

### 2.5 Рецепты — `RecipesView` (`#/recipes`)
- `ensureCatalog()`, `GET /finance/recipe-costs` → `{recipe_id: {per_portion, priced_share}}`.
- Поиск (подстрока по словам или нечёткость ≥ 0,6; при запросе — по похожести, затем по алфавиту), фильтр категории.
- Таблица: имя, «N ингр. · N порц.», категория, выход, ккал/Б/Ж/У на 100 г, «₽/порц.» («+» — цена не всех
  ингредиентов), 🍳 → `CookModal {recipeId}`. Клик → `RecipeModal`; «+ Новый рецепт» → `RecipeModal` пустой.

#### `RecipeModal`
**Просмотр:** категория, порции, выход и порция, время, «можно половиной»; «не в ротации», «✨ эдакое», приёмы пищи,
«хранится N дн.», «❄️ можно заморозить»; КБЖУ/100 г; состав (`variantLabel`, 🎯); инструкция.
Кнопки: «Удалить» (`confirm` «…блюда останутся в холодильнике» → `DELETE /recipes/{id}`), «Изменить», «🍳 Приготовить»
(закрывает и открывает `CookModal`).
**Редактирование:** название, категория (селект) + «новая категория» (`POST /recipes/categories {name}`, Enter/+,
сразу выбирается), `IngredientsEditor exactToggle` (выход для расчёта КБЖУ — указанный или сырой вес), «Выход готового»
(placeholder — сырой вес), «Порций» (1–100), «Время, мин», «Можно готовить половиной» (`allow_half`), «Для автоплана»:
«Предлагать в плане» (`in_rotation`), «❄️ Можно заморозить», «Сложность» easy/special, «Сколько дней можно есть»
(1–14), «Когда уместно» (чекбоксы приёмов; пусто = любой), «Как готовить».
**Сохранение:** «Укажите название», «Выберите или создайте категорию», `resolveDraftIngredients`, «Добавьте ингредиенты»;
`POST /recipes/` или `PATCH /recipes/{id}` с телом `{name, recipe_category_id, default_servings (≥1), allow_half,
in_rotation, effort, meal_types|null, keeps_days (1..14, по умолч. 2), is_freezable, cooking_time_minutes|null,
estimated_cooked_weight (пусто → сырой вес), instructions|null, ingredients[{variant_id, weight_g, exact}]}`,
затем `loadRecipes()`. Новый рецепт: 4 порции, в ротации, easy, одна пустая строка состава.
«Отмена» в правке существующего возвращает к просмотру.

### 2.6 Продукты — `CatalogView` (`#/catalog`)
- Вкладки «Продукты / Товары» (`ft.catalogTab`), «+ Продукт» → `NewProductModal`.
- **Продукты:** поиск по названию, бренду, штрихкоду (подстрока или нечёткость ≥ 0,6), фильтр категории, «N шт.»;
  сортировка категория → название; строка: имя, ⚠ (у активной версии `wrong_nutrients`), «нет КБЖУ» (`kbju_missing`),
  мелко — имя товара (если отличается), бренд, «N производителя», упаковки; КБЖУ первой активной версии. Клик → `ProductModal`.

#### `NewProductModal`
`ProductFinder` (без `kbjuPrompt`) + `OffDraftCard`. Выбор существующего продукта → окно закрывается, открывается его
`ProductModal`, тост «Этот продукт уже есть в справочнике». «Сохранить» (только с черновиком): `draftError`,
`saveDraft(draft, {reuse: false})` (дубль → ошибка сервера), тост «"…" добавлен».

#### `ProductModal`
| Действие | Запрос |
|---|---|
| Штрихкод: поле (8–14 цифр; «Сохранить» видна при изменении; Enter) / 📷 (сохраняет сразу) | `PUT /products/{id}/barcode {barcode}` |
| Единица учёта: граммы / мл / штуки (+ «1 шт = N г») → Сохранить | `PUT /products/{id}/unit {base_unit, piece_weight_g|null}` (общая для всех брендов товара) |
| + Упаковка (сколько, название) | `POST /products/{id}/packages {amount, name|null}` |
| ✕ у упаковки (без подтверждения) | `DELETE /products/packages/{packageId}` |
| «Новые КБЖУ» у производителя (поля предзаполнены активной версией) / «+ Другой производитель» | `POST /products/{id}/variants {manufacturer_name|null, calories, proteins, fats, carbs}` |
| «↶ Откат» (если активная версия > 1; `confirm`) | `POST /products/{id}/manufacturers/{mid}/rollback` |

После каждого — `loadProducts()`. Показывает категорию, бренд, версии КБЖУ по производителям (активная, ⚠ проверить).
⚠️ Нет правки названия/бренда/категории и удаления продукта; объявлен `emit('saved')`, который не вызывается.

#### `ItemsPanel` («Продукты → Товары»)
- `GET /items` → `[{key, name, products[{id, name, brand, base_unit, packages[amount]}]}]`,
  `GET /items/suggestions` → `[{name, items[{key, name, products}]}]`.
- «Похоже на один товар»: название (правится), чекбоксы товаров (по умолчанию все), «Объединить» (≥ 2, иначе тост) →
  `POST /items/merge {keys, name}`; ✕ — скрыть предложение локально (`ft.itemSuggestionsHidden`).
- Поиск (нечёткость ≥ 0,6 по товару и его продуктам). Строка товара: имя, «N бренд.», ✎ → поле + OK/Enter →
  `PATCH /items/{key} {name}`. Продукты товара: бренд · имя · упаковки, ⇄ → `MoveModal`.
- После объединения/переименования/переноса — `load()` + `loadProducts()`.
- ⚠️ `key` подставляется в путь без `encodeURIComponent` (нигде в коде его нет), а ключ — это название в нижнем регистре
  («кефир 3,2%»): `%`, `/`, `?`, `#` в названии сломают `PATCH /items/{key}`.

#### `MoveModal`
Селект «В товар»: другие товары или «+ Новый товар…» (+ название). `PUT /items/products/{productId}
{item_key} | {new_name}`, тост «Продукт перенесён».

### 2.7 Деньги — `MoneyView` (`#/money`)
- Месяц ‹ › (вперёд дальше текущего нельзя). `GET /finance/summary {start_date: 1-е, end_date: последнее}` →
  `{monthly_budget, spent, planned_to_buy, planned_unknown, unpriced_purchases, eaten_value, wasted_value,
  snack_spent, snack_quota, by_category[{name, spent}], waste[{name, reason, value}]}`.
- Бюджет: «Задать/Изменить» → поле → `PUT /finance/budget {monthly_budget|null}` (пусто = снять), затем перезагрузка и
  `loadHousehold()`. Потрачено из бюджета, «осталось / перерасход», полоса (красная при перерасходе);
  только в текущем месяце — «По плану ещё купить ≈ X → к концу месяца ≈ Y» (+ «у N позиций цена неизвестна»).
- Плитки: потрачено (+ «ещё N покупок без цены»), ушло в еду, выброшено (красным, если > 0).
- «Снеки и сладкое» (если тратили или задана квота), «Траты по категориям» (полосы от максимума), «Что выбросили».
- Пустое состояние — «За этот месяц покупок с ценой нет…».

### 2.8 Семья — `FamilyView` (`#/family`)

| Блок / действие | Запрос / правило |
|---|---|
| «Выйти (username)» | локальный выход (1.3) |
| Название семьи → «Сохранить название» (если изменено) | `PATCH /household {name}` → household |
| Код приглашения: «Копировать» | буфер обмена |
| «Новый код» (`confirm` «Старый перестанет работать») | `POST /household/invite-code` → household |
| Допуск по весу 0–30 % (кнопка выкл. вне диапазона/без изменений) | `PATCH /household {portion_tolerance: округлённое}` |
| `PlannerSettingsCard` | см. ниже |
| «Кто ест» — `MemberCard` на каждого (включая скрытых) | см. ниже |
| «Добавить члена семьи без аккаунта»: имя + ккал/день (Enter) | `POST /household/members {name, targets: {calories|null}}` → household; ⚠️ поля очищаются и при ошибке |
| «Пригласить в приложение»: «сразу в нашу семью» + «Создать приглашение» | `POST /household/registration-invites {into_household}` → `{code}`; ссылка `<origin><path>#/register?code=…` копируется в буфер (не вышло — тост «Приглашение создано») |
| список приглашений | `GET /household/registration-invites` → `[{id, code, into_household, used, used_by, expires_at}]`; у неиспользованных «Ссылка» (копировать) и ✕ (`DELETE /household/registration-invites/{id}`, ⚠️ без подтверждения) |
| «Вступить в другую семью»: код (Enter) | `confirm` («…рецепты, холодильник, план и члены семьи без аккаунта переедут туда»), `POST /household/join {invite_code}`, затем `loadHousehold()` + `loadRecipes()` |
| «Оформление» | тема (1.4) |

#### `MemberCard`
- Имя, бейдж «это вы» (`is_me`) / «аккаунт @username» / «без аккаунта», «скрыт»; «Скрыть/Вернуть» только без аккаунта →
  `PATCH /household/members/{id} {is_active}`.
- Цели: ккал, Б, Ж, У (пусто = null).
- «Рассчитать цели…» (`<details>`, открыт, если профиль не заполнен): цель Снижение/Поддержание/Набор, пол, год рождения
  (1920–2010), рост, вес, активность (КФА 1,4 / 1,6 / 1,9 / 2,2; по умолчанию 1,6). «Рассчитать»: нужны пол, год, рост,
  вес → `POST /household/targets/calc {sex, birth_year, height_cm, weight_kg, activity, goal}` → `{targets, bmr,
  maintenance, notes[]}`; цели подставляются в поля (не сохраняются), пояснение «−15 % … / +10 % … / белок 12–14 %,
  жиры 30 %», предупреждения `notes`.
- «Сохранить»: `PATCH /household/members/{id} {name, targets{calories, proteins, fats, carbs}, profile{…}}` → household.
  ⚠️ `emit('saved')` никто не слушает.

#### `PlannerSettingsCard`
- `GET /household/planner` → `{meal_types|null, no_cook_days[], special_days[], max_special_per_week, snack_categories[],
  snack_quota|null}`; `GET /products/categories` (⚠️ дублирует `state.productCategories`).
- Чипы приёмов пищи (минимум один; все выбраны → `null`), «Дни без готовки», «Дни для особых блюд» (0 = пн), «Особых
  блюд в неделю» (0–7), чипы категорий-снеков, «Квота в неделю, ₽» (пусто = null).
- «Сохранить» (активна только при изменениях — сравнение JSON-снимка): `PATCH /household/planner {…}`.

### 2.9 Вход / регистрация — `LoginView`
- `GET /auth/config` → `{registration_mode: open|invite, needs_first_user}`.
- Вкладки «Вход / Регистрация» (по ссылке с `?code` — сразу регистрация с кодом).
- Вход: «Логин или email», пароль. Регистрация: имя, email, пароль, «Код приглашения» (только в режиме `invite`;
  верхний регистр визуально, при отправке `trim`), подсказки про `FIRST_INVITE_CODE` / «код выдаёт тот, кто уже
  пользуется»; в режиме `open` — подсказка про вступление в семью.
- После успеха по ссылке — `history.replaceState(… '#/plan')`, затем `bootstrap`. Ошибки — inline.

---

## 3. Общие компоненты и контракты

### `Modal` (`components.js`)
- Пропсы `title, wide, dismissible`; событие `close`; слоты default и `foot` (подвал только при наличии слота).
- Закрывается **только явно** — ✕ в шапке или кнопкой в подвале. С `dismissible` — ещё по `mousedown` на фоне и по Esc.
  ⚠️ `dismissible` сейчас не передаёт ни один вызов.
- Шапка и подвал закреплены, прокручивается тело (CSS). Вложенные модалки (сканер внутри формы) — рисуются поверх.

### `Picker`
- `items[{id, label, sub?, group?, right?, right2?, keys?}]`, `v-model` (id), `placeholder`, `autofocus`; событие `pick`.
- Фильтр: все слова запроса — подстроки `label + sub + group + keys` (без регистра и «ё»), **или** `fuzzyScore ≥ 0,6`
  по `label + sub`; не больше 80; заголовки групп. Если поле показывает выбранное — список без фильтра.
- Клавиатура: ↓/Enter открывают, ↑↓ подсветка, Enter выбирает, Esc закрывает (без всплытия). Фокус выделяет текст;
  blur через 150 мс закрывает и возвращает подпись выбранного. Крестик (`.clearable`) очищает и держит фокус.
  «Ничего не найдено».

### `ProductFinder` (`product-finder.js`)
- `v-model` = `variant_id`, `v-model:draft` = черновик, `autofocus`, `kbjuPrompt`. Используется: план (продукт),
  ингредиенты, внеплановая покупка, новый продукт.
- Выбрано → карточка «имя + бейдж (старая версия КБЖУ / вручную / Open Food Facts) + подпись» и «Изменить»
  (сбрасывает оба значения, фокус в поиск).
- Поток поиска:
  1. Локально по `activeVariants`: штрихкод (8–14 цифр) — точное совпадение `product.barcode`; иначе `fuzzyScore ≥ 0,6`
     по `name + subFull`, лучшие 30. Справа — ккал и Б/Ж/У или «нет КБЖУ».
  2. Штрихкод и локально пусто → через 250 мс `GET /products/barcode/{code}` → `{source: local|openfoodfacts|none,
     product | suggestion}`: `local` — догрузить справочник при необходимости и выбрать; `openfoodfacts` — одна подсказка
     OFF; `none` — «не нашли ни у нас, ни в OFF».
  3. Текст ≥ 3 и локально пусто → через 900 мс `GET /products/off-search?q` → `{items, local, available}`
     (`local` — уже наши продукты, добавляются в локальные результаты; `available=false` → «OFF сейчас не отвечает»).
     Также по Enter и кнопке «Нет нужного? Искать в Open Food Facts». Ответы устаревших запросов отбрасываются (`seq`).
  4. «✏️ Ввести вручную / Ввести со штрихкодом» → черновик `source: manual` с названием или штрихкодом из поля.
- Выбор OFF → черновик `draftFrom(s)`; выбор своего → `variant_id`, черновик `null`.
- Список прячется по `pointerdown` вне компонента и Esc; снова — фокус/клик/ввод.
- `kbjuPrompt` и у выбранного `kbjuMissing` → форма «У этого продукта ещё нет КБЖУ» (`KbjuInputs`, все 4 обязательны) →
  `POST /products/{productId}/variants {manufacturer_name, …}` → `loadProducts()` → выбор переключается на новую версию.
- Сканер 📷 — `BarcodeScanner` (EAN), код подставляется в поле.

### Черновик продукта: `draftFrom` / `OffDraftCard` / `draftError` / `saveDraft` / `activeVariantOf`
- Черновик: `{source, barcode, searchName, searchBarcode, name, brand, manufacturer, category (ft.lastProductCategory или
  «Готовые продукты»), kbju{4}, package_amount, package_unit}`.
- `OffDraftCard`: название, бренд (пусто = «Без бренда»), категория (datalist), производитель, `KbjuInputs`, упаковка
  (число + г/мл/шт), штрихкод + 📷. Правило: название поменяли относительно найденного — штрихкод найденного товара
  сбрасывается с подсказкой; ручной ввод/скан штрихкода отменяет это правило. `kbjuOptional` — подсказка «можно не заполнять».
- `draftError`: нет названия/категории → ошибка; КБЖУ — все четыре, кроме `kbjuOptional` и пустых всех четырёх.
- `saveDraft(d, {reuse=true})`: `POST /products/with-category {category_name, name, brand_name ('Без бренда'), barcode
  (только 8–14 цифр), package_amount|null, package_unit|null, reuse_existing, base_variant: null (КБЖУ пусты) |
  {manufacturer_name (производитель → бренд → null), calories, proteins, fats, carbs}}`; запоминает категорию,
  `loadProducts()`.
- `activeVariantOf(product, maker)` — активная версия производителя с совпадающим именем, иначе первая активная.

### `IngredientsEditor`
- `v-model` = `[{variant_id, weight_g, draft?, exact?}]`, `cookedWeight`, `exactToggle`. Стабильный ключ строки `_k`.
- Аккордеон: открыт один ингредиент (при открытии — первый пустой); остальные — строка «имя 🎯 / подпись (бренд,
  «старая версия КБЖУ», «нет КБЖУ — нажмите "Изменить"») / вес / Изменить / ✕». Открытый: `ProductFinder kbjuPrompt`,
  вес (г), 🎯 (если `exactToggle`), ✕, `OffDraftCard` черновика, «Готово».
- «+ Добавить ингредиент» (100 г, сразу открыт и в фокусе). Итоги: «N ингр.», «Сырой вес», «На 100 г готового»
  (сумма КБЖУ × 100 / `cookedWeight`; черновики считаются по своим КБЖУ).
- `resolveDraftIngredients(rows)` — вызывать перед отправкой состава: ошибка, если у выбранного нет КБЖУ; проверка
  черновиков (`draftError`, с именем ингредиента); затем `saveDraft` (reuse) и подстановка `variant_id` (мутирует строки).

### `BarcodeScanner`
- Режимы: обычный (EAN-13/8, UPC-A/E — один код и закрытие), `marks` (DataMatrix + EAN, сканирование подряд,
  каждый новый код — событие, повторы того же кода игнорируются, вибрация 60 мс, счётчик `count`, кнопка «Готово»),
  `qr` (QR-код чека). Пропсы `title, count`; события `code`, `close`.
- Движок: `BarcodeDetector` (опрос 300 мс); нет его или нет нужного формата (DataMatrix/QR) → ZXing из
  `vendor/zxing.min.js`, грузится лениво один раз. Камера `facingMode: environment`, только в безопасном контексте
  (иначе — подсказка ввести цифры). Ошибки: нет разрешения / камера недоступна.
- Ручной ввод: обычный — только цифры, ≥ 8 («Найти»); `marks`/`qr` — строка ≥ 10 («Добавить» / «Загрузить»), Enter.
- Камера останавливается при закрытии.

### `KbjuInputs`
Четыре поля на 100 г (`v-model` — объект). Мягкая проверка Атуотера (как на сервере): расхождение ккал с 4Б + 9Ж + 4У
> 10 ккал **и** > 15 % → предупреждение «По БЖУ выходит ≈ N ккал…» (сохранить можно, версия помечается).

### `Macros` / `MacroMeters` / `MemberSwitch`
- `Macros {m, digits=0, kcalOnly}` — «● N ккал · Б · Ж · У» с цветными точками.
- `MacroMeters {value, target}` — 4 полосы «N / цель», ширина ≤ 100 %, класс `over` при > 110 %.
- `MemberSwitch` — сегменты активных членов семьи (только если их > 1), `setViewMember` → `ft.viewMember.<userId>`.

### Форматирование и поиск (`util.js`) — переносить 1:1
- Даты локальные без часовых поясов (`iso`, `parseIso`, `addDays`, `startOfWeek` — пн, `range`), русские форматы дня недели
  и «д ммм» (без точки). ⚠️ «Сегодня» во фронтенде — по часам устройства, на сервере — `APP_TIMEZONE`.
- Числа `ru-RU`; `grams` (≥ 1000 → кг), `fmtQty` (г/кг, мл/л, шт), `fmtMacro` (< 10 — до десятых, нет — «—»), `bjuLine`,
  `packagesLabel` (до двух упаковок, «…», нет — «100 г»), `packageGrams`, `gramsToBase`.
- `norm` (регистр, «ё»→«е», кавычки), `matches` (все слова — подстроки), `fuzzyScore` (целое слово 1, начало 0,9,
  вхождение ≥ 3 симв. 0,85, опечатка ≥ 75 % похожести × 0,8 для слов ≥ 4; среднее по словам запроса) — то же правило,
  что `match_score` на сервере.

---

## 4. Что можно не переносить / упростить

1. **Неиспользуемый код:** `STATUS`, `sumMacros`, `daysBetween` (`util.js`), `portionsSummary` (экспортируется, нигде не
   вызывается), `memberById` в `ItemModal` плана (возвращается из `setup`, в шаблоне нет), `emit('saved')` у `ProductModal`
   и `MemberCard` (никто не слушает), проп `dismissible` у `Modal` (ни одного вызова) — его можно не делать или сделать
   только когда появится окно-«результаты поиска».
2. **Копипаст импортов** после разбиения на файлы: в `views/planner/*`, `plan-modals/*`, `shopping/*` и др. каждый файл
   импортирует один и тот же большой набор (`useAction`, `MacroMeters`, `ensureCatalog`, `ReceiptModal` в `shopping/shared.js`
   и т.д.), большая часть не используется. С TS/ESLint это уйдёт само; файлы-реэкспорты `views/<screen>.js` и `shared.js`
   из одних импортов — не нужны при сборке.
3. **Список модулей в `sw.js` (`SHELL`) и `scripts/check_web.sh`** — нужны только без сборки. В Vite — плагин PWA
   (precache манифеста сборки) и `vue-tsc`/ESLint вместо JavaScriptCore-проверки шаблонов.
4. **Ленивая загрузка ZXing через `<script>`** — заменить динамическим `import()` пакета.
5. **Ключ-заглушка `ft.none`** в `AddItemModal.productDefaults` — заменить явной веткой «нет памяти».
6. **Повторная загрузка категорий** в `PlannerSettingsCard` (`GET /products/categories`) — взять из общего стора.
7. **Алиас `#/profile`** — старый маршрут на ту же «Семью»; можно оставить редиректом, отдельного экрана нет.
8. **Циклы одиночных запросов** («Убрать» черновик, «Прошлая неделя», «Добавить всё» в «Обычно берём», «Инвентаризация»,
   применение чека с новыми продуктами) — переносить как есть, но это кандидаты на bulk-эндпоинты; UI не обязан
   повторять их построчно.
9. **Ручной hash-роутер и ключ перерисовки** — заменить `vue-router` (hash-режим, чтобы не ломать ссылки-приглашения
   `#/register?code=` и ярлыки манифеста `#/plan`, `#/shopping`). Исправить попутно: `#/register` у вошедшего, ключ
   `'shopping'` без query.
10. **Одноимённые `ItemModal`** (план и запасы) — переименовать (`PlanItemModal`, `StockItemModal`).
11. **Исправить при переносе, а не копировать:** нехватка в `CookModal` по `product.name.toLowerCase()` вместо
    `item_key`; `encodeURIComponent` для `/items/{key}`; локальный выход без очистки категорий/очереди; очистка формы
    «Добавить члена семьи» при ошибке; вкладка «Холодильника» не запоминается (в «Продуктах» — запоминается).
12. **`products?limit=2000` / `recipes?limit=500` целиком в память** — так работают поиск и все индексы (`variantIndex`),
    переносить как есть; ограничение — кандидат на серверный поиск позже, но это не задача переноса.
