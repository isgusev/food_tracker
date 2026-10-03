"""Рецепты: список с КБЖУ на 100 г, создание, «приготовил» (холодильник)."""
from __future__ import annotations

import streamlit as st

from ui import api_client


def _variant_options() -> dict[str, int]:
    """Варианты продуктов «Название · Бренд (vN)» -> variant_id."""
    options: dict[str, int] = {}
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
            options[label + f" (v{latest['version']})"] = latest["id"]
    return options


def render() -> None:
    st.header("🍲 Рецепты")

    try:
        categories = api_client.get("recipes/categories") or []
        recipes = api_client.get("recipes/") or []
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    with st.expander("➕ Создать рецепт"):
        cat_names = {c["name"]: c["id"] for c in categories}
        try:
            options = _variant_options()
        except api_client.ApiError as exc:
            st.error(str(exc))
            options = {}
        if not options:
            st.warning("Каталог пуст — сначала добавьте продукты.")
        else:
            with st.form("add_recipe_form", clear_on_submit=True):
                name = st.text_input("Название рецепта *")
                col_a, col_b, col_c = st.columns(3)
                with col_a:
                    category_name = st.selectbox("Категория *", list(cat_names) or [""])
                    servings = st.number_input("Порций", 1, 100, 2)
                with col_b:
                    cooked_weight = st.number_input(
                        "Вес после готовки, г *", 1.0, 9999.0, 600.0, 10.0
                    )
                    time_min = st.number_input("Время готовки, мин", 0, 1440, 30)
                with col_c:
                    st.write("")  # отступ
                instructions = st.text_area("Приготовление")

                st.markdown("**Ингредиенты (на весь рецепт):**")
                ingredient_labels = st.multiselect(
                    "Продукты", list(options), placeholder="Выберите продукты"
                )
                weights: dict[str, float] = {}
                for label in ingredient_labels:
                    weights[label] = st.number_input(
                        f"Вес, г — {label}", 1.0, 9999.0, 100.0, 10.0,
                        key=f"ing_{label}",
                    )

                if st.form_submit_button("Сохранить рецепт"):
                    if not name.strip() or not category_name or not weights:
                        st.warning("Заполните название, категорию и ингредиенты.")
                    else:
                        payload = {
                            "name": name.strip(),
                            "recipe_category_id": cat_names[category_name],
                            "cooking_time_minutes": int(time_min) or None,
                            "instructions": instructions.strip() or None,
                            "default_servings": int(servings),
                            "estimated_cooked_weight": cooked_weight,
                            "ingredients": [
                                {"variant_id": options[l], "weight_g": w}
                                for l, w in weights.items()
                            ],
                        }
                        try:
                            api_client.post("recipes/", payload)
                            st.success(f"Рецепт «{name}» создан.")
                            st.rerun()
                        except api_client.ApiError as exc:
                            st.error(str(exc))

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
                f"готовый: {float(recipe['estimated_cooked_weight']):.0f} г, "
                f"порций: {recipe['default_servings']}"
            )
            if recipe.get("instructions"):
                st.caption(recipe["instructions"])

            col1, col2 = st.columns([1, 3])
            with col1:
                if st.button("🍳 Приготовил", key=f"cook_{recipe['id']}"):
                    st.session_state[f"show_cook_{recipe['id']}"] = True
            with col2:
                try:
                    logs = [
                        lg for lg in api_client.get("recipes/cooking-logs") or []
                        if lg["recipe_id"] == recipe["id"] and not lg["is_finished"]
                    ]
                except api_client.ApiError:
                    logs = []
                for log in logs:
                    st.info(
                        f"В кастрюле: {float(log['current_remaining_weight']):.0f} г"
                    )

            if st.session_state.get(f"show_cook_{recipe['id']}"):
                with st.form(f"cook_form_{recipe['id']}", clear_on_submit=True):
                    total = st.number_input(
                        "Фактический вес готового блюда, г *",
                        1.0, 9999.0,
                        float(recipe["estimated_cooked_weight"]), 10.0,
                    )
                    st.markdown("Состав фактической закладки:")
                    lines: dict[int, float] = {}
                    for line in recipe.get("template_ingredients", []):
                        vid = line["variant_id"]
                        lines[vid] = st.number_input(
                            f"variant #{vid}", 1.0, 9999.0,
                            float(line["weight_g"]), 10.0,
                            key=f"cl_{recipe['id']}_{vid}",
                        )
                    if st.form_submit_button("Записать готовку"):
                        try:
                            api_client.post(
                                f"recipes/{recipe['id']}/cook",
                                {
                                    "total_cooked_weight": total,
                                    "ingredients": [
                                        {"variant_id": v, "weight_g": w}
                                        for v, w in lines.items()
                                    ],
                                },
                            )
                            st.session_state[f"show_cook_{recipe['id']}"] = False
                            st.success("Готовка записана, остатки в холодильнике обновлены.")
                            st.rerun()
                        except api_client.ApiError as exc:
                            st.error(str(exc))
