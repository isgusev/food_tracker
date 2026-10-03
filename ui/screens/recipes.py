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


def _weight_inputs(options: dict[str, dict], selected: list[str]) -> dict[str, float]:
    """Веса ингредиентов. Значения живут в session_state и переживают rerun."""
    weights: dict[str, float] = {}
    cols = st.columns(min(len(selected), 3) or 1)
    for idx, label in enumerate(selected):
        key = f"rc_w_{options[label]['variant_id']}"
        with cols[idx % len(cols)]:
            weights[label] = st.number_input(
                f"Вес, г — {label}", min_value=1.0, max_value=9999.0,
                value=float(st.session_state.get(key, 100.0)), step=10.0, key=key,
            )
    return weights


def _create_form(categories: list[dict]) -> None:
    cat_names = {c["name"]: c["id"] for c in categories}
    try:
        options = _load_options()
    except api_client.ApiError as exc:
        st.error(str(exc))
        return
    if not options:
        st.warning("Каталог пуст — сначала добавьте продукты.")
        return

    name = st.text_input("Название рецепта *", key="rc_name")
    col_a, col_b = st.columns(2)
    with col_a:
        category_name = st.selectbox("Категория *", list(cat_names) or [""], key="rc_cat")
        servings = st.number_input("Порций", 1, 100, 2, key="rc_servings")
    with col_b:
        time_min = st.number_input("Время готовки, мин", 0, 1440, 30, key="rc_time")
    instructions = st.text_area("Приготовление", key="rc_instr")

    st.markdown("**Ингредиенты (на весь рецепт):**")
    search = st.text_input("Поиск продукта", key="rc_search")
    labels = [l for l in options if search.lower() in l.lower()]
    selected = st.multiselect(
        "Продукты (КБЖУ — в таблице ниже)", labels, placeholder="Выберите продукты",
        key="rc_products",
    )
    _nutrition_table(options, selected)

    if not selected:
        st.caption("Выберите продукты — появится таблица КБЖУ и поля для веса.")
        return

    st.markdown("**Вес ингредиентов, г**")
    weights = _weight_inputs(options, selected)

    raw_total = sum(weights.values())
    loss_pct = st.slider(
        "Ужарка/утруска при готовке, %", 0, 50, 15, key="rc_loss",
        help="Процент потери веса при готовке. Используется только как "
             "примерная оценка веса готового блюда. Точный фактический вес "
             "указывается позже, когда блюдо действительно приготовлено.",
    )
    estimated = max(round(raw_total * (100 - loss_pct) / 100, 1), 1.0)
    st.caption(
        f"Сырой вес: **{raw_total:.0f} г** → примерный вес готового: "
        f"**{estimated:.0f} г** (−{loss_pct}%). Фактический вес укажете при готовке."
    )

    if st.button("Сохранить рецепт", type="primary"):
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
                api_client.post("recipes/", payload)
                st.success(f"Рецепт «{name.strip()}» создан.")
                for k in ("rc_products", "rc_search", "rc_name", "rc_instr"):
                    st.session_state.pop(k, None)
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))


def _cooking_block(recipe: dict, names: dict[int, str]) -> None:
    """Фактическая закладка + вес готового. Кастрюль может быть сколько угодно."""
    st.markdown("**Фактическая закладка:**")
    lines: dict[int, float] = {}
    for line in recipe.get("template_ingredients", []):
        vid = line["variant_id"]
        label = names.get(vid, f"продукт #{vid}")
        key = f"cl_{recipe['id']}_{vid}"
        lines[vid] = st.number_input(
            f"{label}, г", min_value=1.0, max_value=9999.0,
            value=float(st.session_state.get(key, float(line["weight_g"]))),
            step=10.0, key=key,
        )
    raw_sum = sum(lines.values())
    default_cooked = min(max(round(raw_sum * 0.85, 1), 1.0), 9999.0)
    cooked_key = f"cooked_total_{recipe['id']}"
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
        if st.button("Записать готовку", type="primary", key=f"save_{recipe['id']}"):
            try:
                api_client.post(
                    f"recipes/{recipe['id']}/cook",
                    {
                        "total_cooked_weight": total,
                        "ingredients": [
                            {"variant_id": v, "weight_g": w} for v, w in lines.items()
                        ],
                    },
                )
                st.session_state[f"show_cook_{recipe['id']}"] = False
                st.success("Готовка записана — блюдо в холодильнике.")
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))
    with bc2:
        if st.button("Отмена", key=f"cancel_{recipe['id']}"):
            st.session_state[f"show_cook_{recipe['id']}"] = False
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
        for product in api_client.get("products/", params={"limit": 500}) or []:
            brand = (product.get("brand") or {}).get("name") or ""
            base = f"{product['name']} · {brand}" if brand else product["name"]
            for mfr in product.get("manufacturers", []):
                for v in mfr.get("variants", []):
                    names[v["id"]] = base
    except api_client.ApiError:
        pass

    with st.expander("➕ Создать рецепт", expanded=False):
        _create_form(categories)

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

            if st.session_state.get(f"show_cook_{recipe['id']}"):
                _cooking_block(recipe, names)
            elif st.button("🍳 Приготовил", key=f"cook_{recipe['id']}"):
                st.session_state[f"show_cook_{recipe['id']}"] = True
                st.rerun()
