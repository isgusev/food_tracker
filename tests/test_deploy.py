"""Готовность к хостингу: регистрация по приглашениям, ограничение попыток входа."""
from __future__ import annotations


import pytest

from app.core.config import get_settings
from tests.test_api import register_and_login

pytestmark = pytest.mark.anyio

FIRST = "START-ME-UP-2026"


@pytest.fixture
def invite_mode(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "registration_mode", "invite")
    monkeypatch.setattr(s, "first_invite_code", FIRST)
    return s


def body(name, code=None):
    return {"username": name, "email": f"{name}@test.com", "password": "secret123", **({"invite_code": code} if code else {})}


async def login(client, name):
    r = await client.post("/api/v1/auth/login", data={"identifier": name, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_invite_only_registration_flow(client, invite_mode):
    cfg = (await client.get("/api/v1/auth/config")).json()
    assert cfg == {"registration_mode": "invite", "needs_first_user": True}

    # без кода и с неверным кодом — нельзя
    assert (await client.post("/api/v1/auth/register", json=body("ivan"))).status_code == 400
    assert (await client.post("/api/v1/auth/register", json=body("ivan", "WRONG"))).status_code == 400
    # первый пользователь — по FIRST_INVITE_CODE с хостинга
    assert (await client.post("/api/v1/auth/register", json=body("ivan", FIRST.lower()))).status_code == 201
    # больше этот код не работает: база уже не пуста
    assert (await client.post("/api/v1/auth/register", json=body("hacker", FIRST))).status_code == 400
    assert (await client.get("/api/v1/auth/config")).json()["needs_first_user"] is False

    ivan = await login(client, "ivan")
    r = await client.post("/api/v1/household/registration-invites", json={"into_household": True}, headers=ivan)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    assert len(code) == 10 and r.json()["into_household"] and not r.json()["used"]

    # жена регистрируется по коду и сразу попадает в семью Ивана
    assert (await client.post("/api/v1/auth/register", json=body("anna", code))).status_code == 201
    anna = await login(client, "anna")
    members = {m["username"] for m in (await client.get("/api/v1/household", headers=anna)).json()["members"]}
    assert members == {"ivan", "anna"}

    # код одноразовый
    assert (await client.post("/api/v1/auth/register", json=body("oleg", code))).status_code == 400
    invites = (await client.get("/api/v1/household/registration-invites", headers=ivan)).json()
    assert invites[0]["used"] and invites[0]["used_by"] == "anna"
    assert (await client.delete(f"/api/v1/household/registration-invites/{invites[0]['id']}", headers=ivan)).status_code == 400

    # приглашение «без семьи»: новый пользователь получит свою семью; отозванное — не работает
    r = await client.post("/api/v1/household/registration-invites", json={"into_household": False}, headers=ivan)
    solo = r.json()
    assert (await client.delete(f"/api/v1/household/registration-invites/{solo['id']}", headers=ivan)).status_code == 204
    assert (await client.post("/api/v1/auth/register", json=body("petr", solo["code"]))).status_code == 400
    r = await client.post("/api/v1/household/registration-invites", json={"into_household": False}, headers=ivan)
    assert (await client.post("/api/v1/auth/register", json=body("petr", r.json()["code"]))).status_code == 201
    petr = await login(client, "petr")
    assert [m["username"] for m in (await client.get("/api/v1/household", headers=petr)).json()["members"]] == ["petr"]


async def test_login_is_rate_limited(client, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "login_max_failures", 3)
    await register_and_login(client, "victim", "victim@test.com")
    for _ in range(3):
        r = await client.post("/api/v1/auth/login", data={"identifier": "victim", "password": "wrong-pass"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", data={"identifier": "victim", "password": "secret123"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    # другой логин с того же адреса не заблокирован
    await register_and_login(client, "other", "other@test.com")


def test_production_requires_invites_and_secret(monkeypatch):
    from app.core.config import Settings

    with pytest.raises(RuntimeError):
        Settings(environment="prod", registration_mode="open", secret_key="x" * 32).validate_runtime()
    with pytest.raises(RuntimeError):
        Settings(environment="prod", registration_mode="invite", secret_key="CHANGE_ME_IN_PRODUCTION").validate_runtime()
    Settings(environment="prod", registration_mode="invite", secret_key="x" * 32).validate_runtime()


def test_postgres_ssl_in_url():
    from app.core.config import Settings

    s = Settings(postgres_ssl="require", database_url_override=None)
    assert s.database_url.endswith("?ssl=require")
    assert "?ssl" not in Settings(postgres_ssl=None, database_url_override=None).database_url


def test_password_with_special_chars_is_escaped():
    from sqlalchemy.engine import make_url

    from app.core.config import Settings

    s = Settings(postgres_password="a/b+c=d@e%f", postgres_ssl="require", database_url_override=None)
    url = make_url(s.database_url)
    assert url.password == "a/b+c=d@e%f" and url.query == {"ssl": "require"}
