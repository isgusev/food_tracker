"""Холодильник: кастрюли (инстансы готовки) и списание в дневник."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from ui import api_client

MEAL_TYPES = {
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "dinner": "Ужин",
    "snack": "Перекус",
}


def _variant_names() -> dict[int, str]:
    """variant_id -> «Название · Бренд» для человекочитаемых заголовков."""
    names: dict[int, str] = {}
    for product in api_client.get("products/", params={"limit": 500}) or []:
        brand = (product.get("brand") or {}).get("name") or ""
        base = f"{product['name']} · {brand}" if brand else product["name"]
        for manufacturer in product.get("manufacturers", []):
            for variant in manufacturer.get("variants", []):
                names[variant["id"]] = base
    return names


def render() -> None:
    st.header("🧊 Холодильник")

    try:
        pots = [p for p in (api_client.get("recipes/cooking-logs") or []) if not p["is_finished"]]
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    if not pots:
        st.info(
            "Холодильник пуст. Приготовьте блюдо во вкладке «Рецепты» — "
            "оно появится здесь, и его можно будет списать в дневник."
        )
        return

    try:
        recipes = api_client.get("recipes/") or []
        names = _variant_names()
    except api_client.ApiError as exc:
        st.error(str(exc))
        return
    recipe_by_id = {r["id"]: r for r in recipes}

    today = dt.date.today().isoformat()

    for pot in pots:
        recipe = recipe_by_id.get(pot["recipe_id"])
        title = (recipe["name"] if recipe else f"Блюдо #{pot['id']}") + \
            f" · осталось {float(pot['current_remaining_weight']):.0f} г"
        with st.expander(f"🍲 {title}"):
            st.write(
                f"Съедобно: **{float(pot['calories_per_100g']):.0f} ккал/100г** · "
                f"приготовлено {float(pot['total_cooked_weight']):.0f} г"
            )
            st.caption("Фактическая закладка:")
            for ing in pot.get("actual_ingredients", []):
                name = names.get(ing["variant_id"], f"продукт #{ing['variant_id']}")
                st.write(f"— {name}: {float(ing['weight_g']):.0f} г")

            c1, c2 = st.columns([2, 1])
            with c1:
                eat_label = f"eat_pot_{pot['id']}"
                if eat_label not in st.session_state:
                    st.session_state[eat_label] = min(
                        float(pot["current_remaining_weight"]), 999.0
                    )
                weight = st.number_input(
                    "Вес порции, г", 1.0, 999.0,
                    value=float(st.session_state[eat_label]), step=10.0,
                    key=f"input_{eat_label}",
                )
                meal_key = f"meal_pot_{pot['id']}"
                if meal_key not in st.session_state:
                    st.session_state[meal_key] = "lunch"
                meal_code = st.selectbox(
                    "Приём пищи", list(MEAL_TYPES),
                    index=list(MEAL_TYPES).index(st.session_state[meal_key]),
                    format_func=lambda v: MEAL_TYPES[v],
                    key=f"sel_{meal_key}",
                )
            with c2:
                st.write("")
                st.write("")
                if st.button("✅ Съел", use_container_width=True, key=f"btn_{pot['id']}"):
                    payload = {
                        "date_day": today,
                        "meal_type": meal_code,
                        "recipe_id": pot["recipe_id"],
                        "weight_g": weight,
                        "servings_multiplier": 1,
                    }
                    try:
                        log = api_client.post("diary/", payload)
                        api_client.post(f"diary/{log['id']}/eat", {"weight_g": weight})
                        st.success(f"Записано в дневник на {today}.")
                        st.rerun()
                    except api_client.ApiError as exc:
                        st.session_state[eat_label] = weight
                        st.session_state[meal_key] = meal_code
                        st.error(str(exc))
