"""Экран входа и регистрации."""
from __future__ import annotations

import streamlit as st

from ui import api_client


def render() -> None:
    st.title("🍎 Food Tracker")

    tab_login, tab_register = st.tabs(["Вход", "Регистрация"])

    with tab_login:
        with st.form("login_form"):
            identifier = st.text_input("Логин или e-mail")
            password = st.text_input("Пароль", type="password")
            if st.form_submit_button("Войти", use_container_width=True):
                try:
                    api_client.login(identifier.strip(), password)
                    st.session_state.pop("auth_error", None)
                    st.rerun()
                except api_client.ApiError as exc:
                    st.session_state["auth_error"] = str(exc)

    with tab_register:
        with st.form("register_form"):
            username = st.text_input("Имя пользователя (от 3 символов)")
            email = st.text_input("E-mail")
            password = st.text_input("Пароль (минимум 8 символов)", type="password")
            if st.form_submit_button("Создать аккаунт", use_container_width=True):
                try:
                    api_client.register(username.strip(), email.strip(), password)
                    st.session_state.pop("auth_error", None)
                    st.rerun()
                except api_client.ApiError as exc:
                    st.session_state["auth_error"] = str(exc)

    error = st.session_state.pop("auth_error", None)
    if error:
        st.error(error)

    st.caption(
        "Демо-доступ (после `python -m scripts.seed`): **demo / demo-pass-123**"
    )
