"""Рецепты: список с КБЖУ, создание (состав + примерный вес), «приготовил».

«Холодильник» (списание готового) вынесен на отдельный экран ui/screens/fridge.py.
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
            options = _load_options()
        except api_client.ApiError as exc:
            st.error(str(exc))
            options = {}
        if not options:
            st.warning("Каталог пуст — сначала добавьте продукты.")
        else:
            name = st.text_input("Название рецепта *")
            col_a, col_b = st.columns(2)
            with col_a:
                category_name = st.selectbox("Категория *", list(cat_names) or [""])
                servings = st.number_input("Порций", 1, 100, 2, key="rc_servings")
            with col_b:
                time_min = st.number_input("Время готовки, мин", 0, 1440, 30, key="rc_time")
            instructions = st.text_area("Приготовление")

            st.markdown("**Ингредиенты (на весь рецепт):**")
            search = st.text_input("Поиск продукта", key="rc_search")
            labels = [l for l in options if search.lower() in l.lower()]
            ingredient_labels = st.multiselect(
                "Продукты", labels, placeholder="Выберите продукты", key="rc_products"
            )
            _nutrition_table(options, ingredient_labels)

            weights: dict[str, float] = {}
            for label in ingredient_labels:
                weights[label] = st.number_input(
                    f"Вес, г — {label}", 1.0, 9999.0, 100.0, 10.0,
                    key=f"ing_{label}",
                )

            raw_total = sum(weights.values())
            loss_pct = st.slider(
                "Ужарка/утруска при готовке, %", 0, 50, 15, key="rc_loss",
                help="Сколько веса теряется при готовке. Вес готового блюда считается "
                     "примерно: сумма ингредиентов минус этот процент. Точный фактический "
                     "вес указывается при приготовке.",
            )
            estimated = max(round(raw_total * (100 - loss_pct) / 100, 1), 1.0)
            st.caption(
                f"Сырой вес: **{raw_total:.0f} г** → примерный вес готового: "
                f"**{estimated:.0f} г** (−{loss_pct}%)"
            )

            if st.button("Сохранить рецепт", type="primary"):
                if not name.strip() or not category_name or not weights:
                    st.warning("Заполните название, категорию и ингредиенты.")
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
                        st.success(f"Рецепт «{name}» создан.")
                        for k in ("rc_products", "rc_search", "rc_loss"):
                            st.session_state.pop(k, None)
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
                f"примерный готовый: {float(recipe['estimated_cooked_weight']):.0f} г, "
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
                        f"В холодильнике по этому рецепту: "
                        f"{float(log['current_remaining_weight']):.0f} г"
                    )

            if st.session_state.get(f"show_cook_{recipe['id']}"):
                st.markdown("**Фактическая закладка:**")
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

                lines: dict[int, float] = {}
                for line in recipe.get("template_ingredients", []):
                    vid = line["variant_id"]
                    label = names.get(vid, f"продукт #{vid}")
                    lines[vid] = st.number_input(
                        f"{label}, г", 1.0, 9999.0,
                        float(line["weight_g"]), 10.0,
                        key=f"cl_{recipe['id']}_{vid}",
                    )
                raw_sum = sum(lines.values())
                default_cooked = min(max(round(raw_sum * 0.85, 1), 1.0), 9999.0)
                cooked_key = f"cooked_total_{recipe['id']}"
                if cooked_key not in st.session_state:
                    st.session_state[cooked_key] = default_cooked
                total = st.number_input(
                    "Фактический вес готового блюда, г *",
                    1.0, 9999.0, value=float(st.session_state[cooked_key]), step=10.0,
                    key=cooked_key,
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
                                        {"variant_id": v, "weight_g": w}
                                        for v, w in lines.items()
                                    ],
                                },
                            )
                            st.session_state[f"show_cook_{recipe['id']}"] = False
                            st.rerun()
                        except api_client.ApiError as exc:
                            st.error(str(exc))
                with bc2:
                    if st.button("Отмена", key=f"cancel_{recipe['id']}"):
                        st.session_state[f"show_cook_{recipe['id']}"] = False
                        st.rerun()
