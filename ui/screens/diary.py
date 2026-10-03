"""Дневник питания: факт и план на день, добавление записей."""
from __future__ import annotations

from datetime import date

import streamlit as st

from ui import api_client

MEAL_TYPES = {
    "breakfast": "Завтрак",
    "lunch": "Обед",
    "dinner": "Ужин",
    "snack": "Перекус",
}


def _recipes() -> list[dict]:
    return api_client.get("recipes/") or []


def _render_day(day: str, title: str) -> None:
    try:
        entries = api_client.get(f"diary/day/{day}") or []
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    planned = [e for e in entries if e["status"] != "fact"]
    eaten = [e for e in entries if e["status"] == "fact"]

    total = lambda rows, key: sum(float(r[key]) for r in rows)  # noqa: E731

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔥 Ккал (факт)", f"{total(eaten, 'calories'):.0f}")
    col2.metric("🥩 Белки", f"{total(eaten, 'proteins'):.1f} г")
    col3.metric("🥑 Жиры", f"{total(eaten, 'fats'):.1f} г")
    col4.metric("🍞 Углеводы", f"{total(eaten, 'carbs'):.1f} г")

    st.subheader(f"{title} — записи ({len(entries)})")
    if not entries:
        st.info("Записей нет.")
        return

    for entry in entries:
        name = entry.get("recipe_name") or f"рецепт #{entry['recipe_id']}"
        status_label = {
            "template_plan": "📝 план (шаблон)",
            "cooked_plan": "🍳 план (факт. кастрюля)",
            "fact": "✅ съедено",
        }.get(entry["status"], entry["status"])
        cols = st.columns([4, 2, 2, 1, 1])
        cols[0].write(
            f"**{MEAL_TYPES.get(entry['meal_type'], entry['meal_type'])}** · {name}"
        )
        cols[1].write(f"{float(entry['weight_g']):.0f} г")
        cols[2].write(
            f"{float(entry['calories']):.0f} ккал · {status_label}"
        )
        with cols[3]:
            if st.button("Съедено", key=f"eat_{entry['id']}", disabled=entry["status"] == "eaten"):
                try:
                    api_client.post(
                        f"diary/{entry['id']}/eat", {"weight_g": float(entry["weight_g"])}
                    )
                    st.rerun()
                except api_client.ApiError as exc:
                    st.error(str(exc))
        with cols[4]:
            if st.button("🗑", key=f"del_{entry['id']}"):
                try:
                    api_client.delete(f"diary/{entry['id']}")
                    st.rerun()
                except api_client.ApiError as exc:
                    st.error(str(exc))


def render() -> None:
    st.header("📅 Дневник питания")

    selected_date = st.date_input("Дата", date.today())
    day = selected_date.isoformat()

    with st.expander("➕ Добавить запись (план или факт)", expanded=False):
        try:
            recipes = _recipes()
        except api_client.ApiError as exc:
            st.error(str(exc))
            recipes = []
        if not recipes:
            st.warning("Нет рецептов — добавьте их во вкладке «Рецепты».")
        else:
            with st.form("add_diary_form", clear_on_submit=True):
                recipe_options = {r["name"]: r["id"] for r in recipes}
                recipe_name = st.selectbox("Рецепт", list(recipe_options))
                meal_key = st.selectbox(
                    "Приём пищи",
                    list(MEAL_TYPES),
                    format_func=lambda k: MEAL_TYPES[k],
                )
                weight = st.number_input("Вес порции, г", 1.0, 999.0, 250.0, 10.0)
                if st.form_submit_button("Добавить в дневник"):
                    try:
                        api_client.post(
                            "diary/",
                            {
                                "date_day": day,
                                "meal_type": meal_key,
                                "recipe_id": recipe_options[recipe_name],
                                "weight_g": weight,
                            },
                        )
                        st.success("Запись добавлена (статус — план).")
                    except api_client.ApiError as exc:
                        st.error(str(exc))

    _render_day(day, day)
