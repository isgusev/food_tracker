"""Рецепты: список с КБЖУ, создание (состав + примерный вес), «приготовил».

UX-решения по замечаниям пользователя:
- КБЖУ продукта видны сразу в таблице выбора (поиск + multiselect);
- введённые веса не сбрасываются при пересборке страницы (ключи стабильны,
  значения хранятся в st.session_state);
- состав можно править до сохранения — таблица весов обновляется на лету;
- вес готового блюда НЕ требуется при создании рецепта: он считается
  приблизительно (сырой вес минус % ужарки); фактический вес указываем
  только когда реально приготовили;
- списание готового («Съел») — на отдельном экране «Холодильник»,
  здесь только запись факта готовки (можно несколько кастрюль).
"""
from __future__ import annotations

import streamlit as st

from ui import api_client


def _load_options() -> dict[str, dict]:
    """label -> {variant_id, ккал/100г, Б, Ж, У} по активным версиям продуктов."""
    options: dict[str, dict] = {}
    for product in api_client.get("products/", params={"limit": 500}) or []:
        brand = (product.get("brand") or {}).get("name") or ""
        for manufacturer in product.get("manufacturers", []):
            variants = sorted(
                manufacturer.get("variants", []), key=lambda v: v["version"]
            )
            if not variants:
                continue
            active = [v for v in variants if v["is_active"]] or [variants[-1]]
            latest = active[-1]
            label = f"{product['name']}"
            if brand:
                label += f" · {brand}"
            options[label + f" (v{latest['version']})"] = {
                "variant_id": latest["id"],
                "calories": float(latest["calories"]),
                "proteins": float(latest["proteins"]),
                "fats": float(latest["fats"]),
                "carbs": float(latest["carbs"]),
            }
    return options


def _variant_options(options: dict[str, dict]) -> dict[str, int]:
    """label -> variant_id (по тому же каталогу, что и _load_options)."""
    return {label: info["variant_id"] for label, info in options.items()}


def _nutrition_table(options: dict[str, dict], selected: list[str]) -> None:
    """КБЖУ выбранных продуктов — чтобы выбирать по составу, а не вслепую."""
    if not selected:
        return
    rows = [
        {
            "Продукт": label,
            "Ккал/100г": round(info["calories"], 1),
            "Б": round(info["proteins"], 1),
            "Ж": round(info["fats"], 1),
            "У": round(info["carbs"], 1),
        }
        for label, info in ((l, options[l]) for l in selected)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _create_form(categories: list[dict], edit_recipe: dict | None = None) -> None:
    """Форма создания/редактирования рецепта. edit_recipe — если режим правки."""
    cat_names = {c["name"]: c["id"] for c in categories}
    id_to_cat = {c["id"]: c["name"] for c in categories}
    try:
        options = _load_options()
    except api_client.ApiError as exc:
        st.error(str(exc))
        return
    if not options:
        st.warning("Каталог пуст — сначала добавьте продукты.")
        return

    editing = edit_recipe is not None
    pfx = "rc" if not editing else f"re{edit_recipe['id']}"

    # При первом открытии формы (создание или правка) принудительно
    # очищаем её поля, чтобы не показывать данные предыдущей сессии/рецепта.
    open_key = f"{pfx}_opened"
    if not st.session_state.get(open_key):
        for k in list(st.session_state.keys()):
            if k.startswith(f"{pfx}_"):
                st.session_state.pop(k, None)
        st.session_state[open_key] = True

    # Значения полей живут только в session_state (у виджетов есть key),
    # поэтому value передаём как статический default при ПЕРВОМ создании
    # виджета. Никаких записей в st.session_state[key_виджета] после этого —
    # иначе Streamlit ругается («default value + Session State API»).
    ed = edit_recipe or {}

    name = st.text_input(
        "Название рецепта *", key=f"{pfx}_name", value=ed.get("name", ""),
    )
    col_a, col_b = st.columns(2)
    with col_a:
        default_cat = id_to_cat.get(ed.get("recipe_category_id"), "") if editing else ""
        if default_cat and default_cat not in cat_names:
            default_cat = ""
        cat_options = [default_cat] + [n for n in cat_names if n != default_cat] if default_cat else list(cat_names)
        category_name = st.selectbox(
            "Категория *", cat_options or [""], key=f"{pfx}_cat",
        )
        servings = st.number_input(
            "Порций", 1, 100, int(ed.get("default_servings") or 2),
            key=f"{pfx}_servings",
        )
    with col_b:
        time_min = st.number_input(
            "Время готовки, мин", 0, 1440, int(ed.get("cooking_time_minutes") or 30),
            key=f"{pfx}_time",
        )
    instructions = st.text_area(
        "Приготовление", key=f"{pfx}_instr", value=ed.get("instructions") or "",
    )

    st.markdown("**Ингредиенты (на весь рецепт):**")
    search = st.text_input("Поиск продукта", key=f"{pfx}_search")
    labels = [l for l in options if search.lower() in l.lower()]

    # В режиме правки — заранее выбранные продукты и их веса из шаблона
    default_selected: list[str] = []
    prefill_weights: dict[int, float] = {}
    if editing:
        vid_to_label = {info["variant_id"]: l for l, info in options.items()}
        for line in edit_recipe.get("template_ingredients", []):
            lbl = vid_to_label.get(line["variant_id"])
            if lbl:
                default_selected.append(lbl)
                prefill_weights[line["variant_id"]] = float(line["weight_g"])

    selected = st.multiselect(
        "Продукты (КБЖУ — в таблице ниже)", labels, placeholder="Выберите продукты",
        key=f"{pfx}_products", default=default_selected,
    )
    _nutrition_table(options, selected)

    if not selected:
        st.caption("Выберите продукты — появится таблица КБЖУ и поля для веса.")
        return

    st.markdown("**Вес ингредиентов, г**")
    weights: dict[str, float] = {}
    cols = st.columns(min(len(selected), 3) or 1)
    for idx, label in enumerate(selected):
        vid = options[label]["variant_id"]
        # КЛЮЧ не содержит префикс формы: одно и то же поле переживает
        # rerun и сохранение/сброс формы, вес не теряется.
        key = f"rc_w_{vid}"
        default_w = prefill_weights.get(vid, 100.0)
        with cols[idx % len(cols)]:
            weights[label] = st.number_input(
                f"Вес, г — {label}", min_value=1.0, max_value=9999.0,
                value=float(st.session_state.get(key, default_w)), step=10.0, key=key,
            )

    raw_total = sum(weights.values())
    loss_pct = st.slider(
        "Ужарка/утруска при готовке, %", 0, 50, 15, key=f"{pfx}_loss",
        help="Процент потери веса при готовке. Используется только как "
             "примерная оценка веса готового блюда. Точный фактический вес "
             "указывается позже, когда блюдо действительно приготовлено.",
    )
    estimated = max(round(raw_total * (100 - loss_pct) / 100, 1), 1.0)
    st.caption(
        f"Сырой вес: **{raw_total:.0f} г** → примерный вес готового: "
        f"**{estimated:.0f} г** (−{loss_pct}%). Фактический вес укажете при готовке."
    )

    bc1, bc2 = st.columns(2)
    with bc1:
        btn_label = "💾 Сохранить изменения" if editing else "Сохранить рецепт"
        if st.button(btn_label, type="primary", key=f"{pfx}_save"):
            if not name.strip() or not category_name:
                st.warning("Заполните название и категорию.")
            else:
                payload = {
                    "name": name.strip(),
                    "recipe_category_id": cat_names[category_name],
                    "cooking_time_minutes": int(time_min) or None,
                    "instructions": instructions.strip() or None,
                    "default_servings": int(servings),
                    "estimated_cooked_weight": estimated,
                    "ingredients": [
                        {"variant_id": options[l]["variant_id"], "weight_g": w}
                        for l, w in weights.items()
                    ],
                }
                try:
                    if editing:
                        api_client.patch(f"recipes/{edit_recipe['id']}", payload)
                        # сбрасываем кэш полей формы правки
                        for k in list(st.session_state.keys()):
                            if k.startswith(pfx):
                                st.session_state.pop(k, None)
                        st.session_state.pop("edit_recipe_id", None)
                        st.toast(f"Рецепт «{name.strip()}» обновлён ✅")
                    else:
                        api_client.post("recipes/", payload)
                        # очищаем форму и сворачиваем её
                        for k in list(st.session_state.keys()):
                            if k.startswith("rc_"):
                                st.session_state.pop(k, None)
                        st.session_state.pop("show_create", None)
                        st.session_state["just_saved"] = name.strip()
                    st.rerun()
                except api_client.ApiError as exc:
                    st.error(str(exc))
    with bc2:
        if editing and st.button("Отмена", key=f"{pfx}_cancel"):
            for k in list(st.session_state.keys()):
                if k.startswith(pfx):
                    st.session_state.pop(k, None)
            st.session_state.pop("edit_recipe_id", None)
            st.rerun()


def _cooking_block(recipe: dict, names: dict[int, str], options: dict[str, dict]) -> None:
    """Фактическая закладка: черновик с добавлением/удалением ингредиентов.

    Черновик (draft) живёт в session_state: изменения веса и состава НЕ
    сбрасываются при rerun, пока пользователь не нажмёт «Записать готовку»
    или «Отмена». Вес готового блюда предзаполняется суммой сырья минус 15%
    усушки — его можно изменить вручную после взвешивания.
    """
    rid = recipe["id"]
    draft_key = f"cook_draft_{rid}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = {
            line["variant_id"]: float(line["weight_g"])
            for line in recipe.get("template_ingredients", [])
        }
    draft: dict[int, float] = st.session_state[draft_key]

    st.markdown("**Фактическая закладка:**")
    if draft:
        vids = list(draft.keys())
        cols_per_row = 3
        for i in range(0, len(vids), cols_per_row):
            row_cols = st.columns(cols_per_row + 1)
            for j, vid in enumerate(vids[i:i + cols_per_row]):
                label = names.get(vid, f"продукт #{vid}")
                with row_cols[j]:
                    draft[vid] = row_cols[j].number_input(
                        f"{label}, г", min_value=1.0, max_value=9999.0,
                        value=float(draft[vid]), step=10.0,
                        key=f"ckw_{rid}_{vid}",
                    )
                with row_cols[cols_per_row]:
                    if st.button("✖", key=f"ckm_{rid}_{vid}", help="Убрать ингредиент"):
                        draft.pop(vid, None)
                        st.session_state.pop(f"ckw_{rid}_{vid}", None)
                        st.rerun()

    # добавить продукт, которого ещё нет в закладке
    existing_labels = {l for l, vid in _variant_options(options).items() if vid in draft}
    free_labels = [l for l in options if l not in existing_labels]
    if free_labels:
        add_col1, add_col2, add_col3 = st.columns([3, 1, 1])
        with add_col1:
            chosen = st.selectbox("Добавить продукт", free_labels, key=f"ckadd_sel_{rid}")
        with add_col2:
            add_w = st.number_input("Вес, г", 1.0, 9999.0, 100.0, step=10.0,
                                    key=f"ckadd_w_{rid}")
        with add_col3:
            st.write("")
            st.write("")
            if st.button("➕", key=f"ckadd_btn_{rid}"):
                draft[_variant_options(options)[chosen]] = float(add_w)
                st.rerun()

    raw_sum = sum(draft.values())
    default_cooked = min(max(round(raw_sum * 0.85, 1), 1.0), 9999.0)
    cooked_key = f"cooked_total_{rid}"
    total = st.number_input(
        "Фактический вес готового блюда, г *",
        min_value=1.0, max_value=9999.0,
        value=float(st.session_state.get(cooked_key, default_cooked)),
        step=10.0, key=cooked_key,
        help=f"Сырьё: {raw_sum:.0f} г. Если не взвешивали — оставьте "
             f"примерную оценку ({default_cooked:.0f} г ≈ −15%).",
    )

    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("Записать готовку", type="primary", key=f"save_{rid}",
                     disabled=not draft):
            try:
                api_client.post(
                    f"recipes/{rid}/cook",
                    {
                        "total_cooked_weight": total,
                        "ingredients": [
                            {"variant_id": v, "weight_g": w} for v, w in draft.items()
                        ],
                    },
                )
                st.session_state[f"show_cook_{rid}"] = False
                st.session_state.pop(draft_key, None)
                st.success("Готовка записана — блюдо в холодильнике.")
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))
    with bc2:
        if st.button("Отмена", key=f"cancel_{rid}"):
            st.session_state[f"show_cook_{rid}"] = False
            st.session_state.pop(draft_key, None)
            st.rerun()


def render() -> None:
    st.header("🍲 Рецепты")

    try:
        categories = api_client.get("recipes/categories") or []
        recipes = api_client.get("recipes/") or []
        pots = [
            p for p in (api_client.get("recipes/cooking-logs") or [])
            if not p["is_finished"]
        ]
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    # имена продуктов для человекочитаемых заголовков (вместо «продукт #id»)
    names: dict[int, str] = {}
    try:
        options = _load_options()  # label -> {variant_id, КБЖУ}
        for product in api_client.get("products/", params={"limit": 500}) or []:
            brand = (product.get("brand") or {}).get("name") or ""
            base = f"{product['name']} · {brand}" if brand else product["name"]
            for mfr in product.get("manufacturers", []):
                for v in mfr.get("variants", []):
                    names[v["id"]] = base
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    # --- Форма создания (раскрывается кнопкой, сворачивается после сохранения) ---
    just_saved = st.session_state.pop("just_saved", None)
    if just_saved:
        st.success(f"✅ Рецепт «{just_saved}» сохранён.")

    edit_id = st.session_state.get("edit_recipe_id")
    edit_recipe = next((r for r in recipes if r["id"] == edit_id), None) if edit_id else None

    if st.button("➕ Создать рецепт", disabled=edit_recipe is not None):
        st.session_state["show_create"] = True

    show_create = bool(st.session_state.get("show_create")) and edit_recipe is None
    with st.expander("Форма нового рецепта", expanded=show_create):
        if show_create:
            _create_form(categories)
        else:
            st.caption('Нажмите «➕ Создать рецепт», чтобы заполнить форму.')

    # --- Режим редактирования выбранного рецепта ---
    if edit_recipe is not None:
        st.subheader(f"✏️ Изменение рецепта «{edit_recipe['name']}»")
        _create_form(categories, edit_recipe=edit_recipe)

    if not recipes:
        st.info("Рецептов пока нет.")
        return

    for recipe in recipes:
        title = f"{recipe['name']} · {float(recipe['calories_per_100g']):.0f} ккал/100г"
        with st.expander(title):
            st.write(
                f"Б {float(recipe['proteins_per_100g']):.1f} · "
                f"Ж {float(recipe['fats_per_100g']):.1f} · "
                f"У {float(recipe['carbs_per_100g']):.1f} (на 100 г)"
            )
            st.write(
                f"Сырой вес: {float(recipe['total_raw_weight']):.0f} г → "
                f"примерный готовый: {float(recipe['estimated_cooked_weight']):.0f} г, "
                f"порций: {recipe['default_servings']}"
            )
            if recipe.get("instructions"):
                st.caption(recipe["instructions"])

            st.markdown("**Состав:**")
            for ing in recipe.get("template_ingredients", []):
                label = names.get(ing["variant_id"], f"продукт #{ing['variant_id']}")
                st.write(f"— {label}: {float(ing['weight_g']):.0f} г")

            my_pots = [p for p in pots if p["recipe_id"] == recipe["id"]]
            if my_pots:
                total_left = sum(float(p["current_remaining_weight"]) for p in my_pots)
                st.info(
                    f"🧊 В холодильнике: {len(my_pots)} шт. · всего {total_left:.0f} г "
                    f"(списание — во вкладке «Холодильник»)"
                )

            ac1, ac2, ac3 = st.columns([1, 1, 2])
            with ac1:
                if st.session_state.get(f"show_cook_{recipe['id']}"):
                    pass  # форма готовки ниже
                elif st.button("🍳 Приготовил", key=f"cook_{recipe['id']}",
                               disabled=st.session_state.get("edit_recipe_id") == recipe["id"]):
                    st.session_state[f"show_cook_{recipe['id']}"] = True
                    st.rerun()
            with ac2:
                if st.button("✏️ Изменить", key=f"edit_{recipe['id']}",
                             disabled=st.session_state.get("edit_recipe_id") == recipe["id"]):
                    st.session_state["edit_recipe_id"] = recipe["id"]
                    st.session_state.pop("show_create", None)
                    st.rerun()
            with ac3:
                if st.button("🗑 Удалить", key=f"del_{recipe['id']}"):
                    st.session_state[f"confirm_del_{recipe['id']}"] = True

            if st.session_state.get(f"confirm_del_{recipe['id']}"):
                st.warning(f"Удалить рецепт «{recipe['name']}»? Приготовленные кастрюли останутся в холодильнике.")
                dc1, dc2 = st.columns(2)
                with dc1:
                    if st.button("Да, удалить", key=f"del_yes_{recipe['id']}", type="primary"):
                        try:
                            api_client.delete(f"recipes/{recipe['id']}")
                            st.session_state.pop(f"confirm_del_{recipe['id']}", None)
                            if st.session_state.get("edit_recipe_id") == recipe["id"]:
                                st.session_state.pop("edit_recipe_id", None)
                            st.toast("Рецепт удалён")
                            st.rerun()
                        except api_client.ApiError as exc:
                            st.error(str(exc))
                with dc2:
                    if st.button("Отмена", key=f"del_no_{recipe['id']}"):
                        st.session_state.pop(f"confirm_del_{recipe['id']}", None)
                        st.rerun()

            if st.session_state.get(f"show_cook_{recipe['id']}"):
                _cooking_block(recipe, names, options)
