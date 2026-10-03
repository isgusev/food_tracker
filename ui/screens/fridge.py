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


def _variant_options() -> dict[str, int]:
    """label -> variant_id по активным версиям продуктов."""
    opts: dict[str, int] = {}
    for product in api_client.get("products/", params={"limit": 500}) or []:
        brand = (product.get("brand") or {}).get("name") or ""
        for manufacturer in product.get("manufacturers", []):
            variants = sorted(manufacturer.get("variants", []), key=lambda v: v["version"])
            if not variants:
                continue
            active = [v for v in variants if v["is_active"]] or [variants[-1]]
            latest = active[-1]
            label = f"{product['name']}"
            if brand:
                label += f" · {brand}"
            opts[label + f" (v{latest['version']})"] = latest["id"]
    return opts


def _ingredient_editor(pot: dict, names: dict[int, str]) -> None:
    """Правка фактической закладки кастрюли: добавить / убрать / заменить ингредиент.

    Работает как черновик: изменения применяются кнопкой «Применить» (PUT полной
    замены списка). КБЖУ кастрюли сервер пересчитывает автоматически; остаток
    еды не меняется — меняются только ингредиенты и их веса.
    """
    st.info("Редактор состава: измените веса, уберите или добавьте продукты, затем «Применить».")
    try:
        options = _variant_options()
    except api_client.ApiError as exc:
        st.error(str(exc))
        return
    label_by_vid = {}
    for l, vid in options.items():
        label_by_vid.setdefault(vid, l)

    draft_key = f"draft_{pot['id']}"
    if draft_key not in st.session_state:
        st.session_state[draft_key] = {
            ing["variant_id"]: float(ing["weight_g"])
            for ing in pot.get("actual_ingredients", [])
        }
    draft: dict[int, float] = st.session_state[draft_key]

    # существующие строки: вес + галочка «оставить»
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
                        key=f"edi_{pot['id']}_{vid}",
                    )
                with row_cols[cols_per_row]:
                    if st.button("✖", key=f"edm_{pot['id']}_{vid}", help="Убрать ингредиент"):
                        draft.pop(vid, None)
                        st.session_state.pop(f"edi_{pot['id']}_{vid}", None)
                        st.rerun()

    # добавить новый продукт (не занятый в кастрюле)
    free_labels = [l for l, vid in options.items() if vid not in draft]
    if free_labels:
        add_col1, add_col2, add_col3 = st.columns([3, 1, 1])
        with add_col1:
            chosen = st.selectbox("Добавить продукт", free_labels, key=f"add_sel_{pot['id']}")
        with add_col2:
            add_w = st.number_input("Вес, г", 1.0, 9999.0, 100.0, step=10.0,
                                    key=f"add_w_{pot['id']}")
        with add_col3:
            st.write("")
            st.write("")
            if st.button("➕", key=f"add_btn_{pot['id']}"):
                draft[options[chosen]] = float(add_w)
                st.rerun()

    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("💾 Применить", type="primary", key=f"apply_{pot['id']}",
                     disabled=not draft):
            payload = {"ingredients": [{"variant_id": v, "weight_g": w}
                                       for v, w in draft.items()]}
            try:
                api_client.put(f"recipes/cooking-logs/{pot['id']}/ingredients", payload)
                st.session_state.pop(draft_key, None)
                st.session_state.pop(f"edit_ing_{pot['id']}", None)
                st.success("Состав обновлён, КБЖУ пересчитаны.")
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))
    with bc2:
        if st.button("Отмена", key=f"cancel_{pot['id']}"):
            st.session_state.pop(draft_key, None)
            st.session_state.pop(f"edit_ing_{pot['id']}", None)
            st.rerun()


def render() -> None:  # noqa: C901 — большой UI-блок, сознательно один экран
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

            # --- Редактирование фактической закладки (добавить/убрать/заменить) ---
            if st.session_state.get(f"edit_ing_{pot['id']}"):
                _ingredient_editor(pot, names)

            c1, c2, c3 = st.columns([2, 1, 1])
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
                if st.button("🔧 Изменить состав", use_container_width=True,
                             key=f"editbtn_{pot['id']}"):
                    st.session_state[f"edit_ing_{pot['id']}"] = not st.session_state.get(
                        f"edit_ing_{pot['id']}", False
                    )
                    st.rerun()
            with c2:
                meal_key = f"meal_pot_{pot['id']}"
                if meal_key not in st.session_state:
                    st.session_state[meal_key] = "lunch"
                meal_code = st.selectbox(
                    "Приём пищи", list(MEAL_TYPES),
                    index=list(MEAL_TYPES).index(st.session_state[meal_key]),
                    format_func=lambda v: MEAL_TYPES[v],
                    key=f"sel_{meal_key}",
                )
            with c3:
                # ручное число порций: перемножаем вес съеденного
                srv_key = f"srv_pot_{pot['id']}"
                if srv_key not in st.session_state:
                    st.session_state[srv_key] = 1
                servings = st.number_input(
                    "Порций", 1, 20,
                    value=int(st.session_state[srv_key]), step=1,
                    key=f"sel_srv_{pot['id']}",
                    help="Сколько таких порций съесть (вес умножается на это число).",
                )

            if st.button("✅ Съел", use_container_width=True, key=f"btn_{pot['id']}"):
                total_eaten = min(weight * int(servings), float(pot["current_remaining_weight"]))
                payload = {
                    "date_day": today,
                    "meal_type": meal_code,
                    "recipe_id": pot["recipe_id"],
                    "weight_g": round(total_eaten, 1),
                    "servings_multiplier": int(servings),
                }
                try:
                    log = api_client.post("diary/", payload)
                    api_client.post(f"diary/{log['id']}/eat", {"weight_g": round(total_eaten, 1)})
                    st.success(f"Записано в дневник на {today}.")
                    st.rerun()
                except api_client.ApiError as exc:
                    st.session_state[eat_label] = weight
                    st.session_state[meal_key] = meal_code
                    st.session_state[srv_key] = int(servings)
                    st.error(str(exc))
