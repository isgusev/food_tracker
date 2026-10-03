"""Food Tracker UI — Streamlit-приложение поверх REST API (JWT).

Транспорт запросов — ui/api_client.py, экраны — ui/screens/*.
Бизнес-логика целиком на бэкенде; здесь только представление.
"""
from __future__ import annotations

import streamlit as st

from ui import api_client
from ui.screens import auth, catalog, diary, fridge, recipes, shopping

st.set_page_config(
    page_title="Food Tracker", layout="wide", initial_sidebar_state="expanded"
)

if not api_client.is_authenticated():
    auth.render()
    st.stop()

menu = st.sidebar.radio(
    "Навигация",
    [
        "📅 Дневник питания",
        "🧊 Холодильник",
        "🍲 Рецепты",
        "🛒 Список покупок",
        "📦 Каталог продуктов",
    ],
)

with st.sidebar:
    st.write(f"👤 **{api_client.current_username()}**")
    if st.button("Выйти", use_container_width=True):
        api_client.clear_session()
        st.rerun()

screens = {
    "📅 Дневник питания": diary.render,
    "🧊 Холодильник": fridge.render,
    "🍲 Рецепты": recipes.render,
    "🛒 Список покупок": shopping.render,
    "📦 Каталог продуктов": catalog.render,
}

try:
    screens[menu]()
except api_client.ApiError as exc:
    if exc.status_code == 401:
        st.warning("Сессия истекла — войдите заново.")
        st.rerun()
    st.error(str(exc))
