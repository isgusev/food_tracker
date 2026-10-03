"""Список покупок из планов дневника на период."""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from ui import api_client


def render() -> None:
    st.header("🛒 Список покупок")

    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("С даты", date.today())
    with col2:
        end = st.date_input("По дату", date.today() + timedelta(days=6))

    if (end - start).days > 90:
        st.warning("Период не должен превышать 90 дней.")
        return

    try:
        data = api_client.get(
            "diary/shopping-list",
            params={"start_date": start.isoformat(), "end_date": end.isoformat()},
        )
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    items = (data or {}).get("items", [])
    if not items:
        st.info("На выбранный период планов нет — список пуст.")
        return

    st.caption(f"{data['start_date']} → {data['end_date']}")
    rows = [
        {"Продукт": i["product_name"], "Нужно, г": round(float(i["weight_g"]), 1)}
        for i in items
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇️ Скачать CSV",
        "\n".join(
            ["product,weight_g"]
            + [f"\"{r['Продукт']}\",{r['Нужно, г']}" for r in rows]
        ),
        file_name="shopping_list.csv",
        mime="text/csv",
    )
