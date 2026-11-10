"""Клиент code-qr.ru: строка QR кассового чека → позиции чека (данные ФНС).

Два вызова: add-qr (поставить чек в очередь, получить hash) и info (статус и
позиции по hash). Чеки доходят до ФНС с задержкой — статусы wait/process нормальны.
Сеть и ошибки сервиса превращаются в доменные ошибки, а не в 500.
Тесты подменяют add_qr/info (monkeypatch) — в тестах сети нет.
"""
from __future__ import annotations


import httpx

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError, ValidationError

TIMEOUT = 10.0
HEADERS = {"User-Agent": "FoodTracker/1.0 (family meal planner)"}


def _auth(key: str) -> tuple[dict[str, str], dict[str, str]]:
    """Как передать ключ code-qr.ru — ЕДИНСТВЕННОЕ место, где это решается.

    Проверено реальным запросом: ключ передаётся в HTTP-заголовке «key: <ключ>».
    Сам ключ — только в настройках (CODEQR_API_KEY), в коде и тестах его нет.
    Возвращается пара (заголовки, параметры запроса).
    """
    return {"key": key}, {}


def _key() -> str:
    key = (get_settings().codeqr_api_key or "").strip()
    if not key:
        raise ServiceUnavailableError("Импорт чеков не настроен: нет ключа CODEQR_API_KEY")
    return key


async def _call(method: str, path: str, *, params: dict | None = None, data: dict | None = None) -> dict:
    headers, auth_params = _auth(_key())
    url = get_settings().codeqr_base_url.rstrip("/") + path
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
            r = await client.request(
                method, url, params={**(params or {}), **auth_params} or None, data=data, headers=headers
            )
    except httpx.HTTPError:
        raise ServiceUnavailableError("Сервис чеков code-qr.ru не отвечает — попробуйте позже") from None
    if r.status_code in (401, 403):
        raise ServiceUnavailableError("Сервис чеков отклонил ключ CODEQR_API_KEY — проверьте его")
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise ServiceUnavailableError(f"Сервис чеков ответил ошибкой ({r.status_code}) — попробуйте позже")
    return body


async def add_qr(qr: str) -> str:
    """Поставить чек в очередь на расшифровку → hash для последующих запросов."""
    body = await _call("POST", "/receipt/add-qr", data={"qr": qr})
    if not body.get("success") or not body.get("hash"):
        # сообщение сервиса — как есть («Нет активного пакета доступа к API проверки чеков», …)
        raise ValidationError(f"Сервис чеков: {body.get('message') or 'неизвестная ошибка'}")
    return str(body["hash"])


async def info(receipt_hash: str) -> dict:
    """Сырой ответ по чеку: success, status (done|wait|process|error), t, s, result{user, user_inn, items}."""
    return await _call("GET", "/receipt/info", params={"hash": receipt_hash})
