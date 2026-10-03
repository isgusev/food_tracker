"""HTTP-клиент Food Tracker API для Streamlit UI.

Отвечает только за транспорт: базовый URL, JWT-токен (сохраняется в
st.session_state), разбор ошибок FastAPI в человекочитаемый текст.
Никакой бизнес-логики здесь нет — она живёт на бэкенде.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import requests
import streamlit as st

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
API_PREFIX = "/api/v1"
_TOKEN_KEY = "jwt_token"
_USER_KEY = "auth_user"


class ApiError(Exception):
    """Ошибка API с человекочитаемым сообщением."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"[{status_code}] {detail}")
        self.status_code = status_code
        self.detail = detail


def base_url() -> str:
    return os.environ.get("FOOD_TRACKER_API_URL", DEFAULT_BASE_URL).rstrip("/")


def _extract_detail(resp: requests.Response) -> str:
    """Достаёт текст ошибки из ответа FastAPI (dict/str/list форматы detail)."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300] or f"HTTP {resp.status_code}"
    detail = body.get("detail", body)
    if isinstance(detail, list):  # 422: pydantic errors
        parts = []
        for err in detail:
            loc = ".".join(str(x) for x in err.get("loc", []) if x != "body")
            parts.append(f"{loc}: {err.get('msg', '')}".strip(": "))
        return "; ".join(parts) or resp.text[:300]
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)


def auth_header() -> Optional[dict]:
    token = st.session_state.get(_TOKEN_KEY)
    return {"Authorization": f"Bearer {token}"} if token else None


def set_session(token: str, username: str) -> None:
    st.session_state[_TOKEN_KEY] = token
    st.session_state[_USER_KEY] = username


def clear_session() -> None:
    st.session_state.pop(_TOKEN_KEY, None)
    st.session_state.pop(_USER_KEY, None)


def is_authenticated() -> bool:
    return bool(st.session_state.get(_TOKEN_KEY))


def current_username() -> str:
    return st.session_state.get(_USER_KEY, "")


def login(identifier: str, password: str) -> None:
    """Логин через /auth/login (form-data). Бросает ApiError при отказе."""
    resp = requests.post(
        f"{base_url()}{API_PREFIX}/auth/login",
        data={"identifier": identifier, "password": password},
        timeout=15,
    )
    if resp.status_code != 200:
        raise ApiError(resp.status_code, _extract_detail(resp))
    payload = resp.json()
    set_session(payload["access_token"], identifier)


def register(username: str, email: str, password: str) -> None:
    resp = requests.post(
        f"{base_url()}{API_PREFIX}/auth/register",
        json={"username": username, "email": email, "password": password},
        timeout=15,
    )
    if resp.status_code not in (200, 201):
        raise ApiError(resp.status_code, _extract_detail(resp))
    login(username, password)


def request_json(method: str, endpoint: str, *, params: dict | None = None,
                 json_body: dict | None = None, expect_none: bool = False) -> Any:
    """Единая точка выхода в API. Возвращает JSON или None (204)."""
    url = f"{base_url()}{API_PREFIX}/{endpoint.lstrip('/')}"
    headers = auth_header() or {}
    try:
        resp = requests.request(method, url, params=params, json=json_body,
                                headers=headers, timeout=30)
    except requests.ConnectionError as exc:
        raise ApiError(0, f"Сервер недоступен ({base_url()}). Запущен ли uvicorn?") from exc
    if resp.status_code == 401:
        clear_session()
        raise ApiError(401, "Сессия истекла — войдите заново")
    if resp.status_code >= 400:
        raise ApiError(resp.status_code, _extract_detail(resp))
    if expect_none or resp.status_code == 204:
        return None
    if not resp.content:
        return None
    return resp.json()


def get(endpoint: str, params: dict | None = None) -> Any:
    return request_json("GET", endpoint, params=params)


def post(endpoint: str, json_body: dict | None = None) -> Any:
    return request_json("POST", endpoint, json_body=json_body)


def patch(endpoint: str, json_body: dict | None = None) -> Any:
    return request_json("PATCH", endpoint, json_body=json_body)


def delete(endpoint: str) -> Any:
    return request_json("DELETE", endpoint, expect_none=True)
