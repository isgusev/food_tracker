"""Коды «Честного знака»: разбор GS1 DataMatrix, добавление в запасы по пачкам,
разные сроки — разные партии, повторный скан той же пачки запрещён."""
from __future__ import annotations


from datetime import date, datetime

import pytest

from app.services.marking import parse_mark
from tests.test_api import day, register_and_login

pytestmark = pytest.mark.anyio

GS = "\x1d"
GTIN = "04607084350150"            # штрихкод 4607084350150


def code(serial: str, expiry: str | None = None, *, gs: bool = True, short: bool = False) -> str:
    sep = GS if gs else ""
    tail = ""
    if expiry:
        tail = sep + (("7003" + expiry) if short else ("17" + expiry))
    return f"01{GTIN}21{serial}{tail}{sep}93AbCd"


def test_parse_mark_variants():
    m = parse_mark(code("5abcDE", "261020"))
    assert (m.gtin, m.barcode, m.serial, m.expires_on) == (GTIN, "4607084350150", "5abcDE", date(2026, 10, 20))
    # 13-символьный серийный номер, без срока
    m = parse_mark(code("abcdefghij123"))
    assert m.serial == "abcdefghij123" and m.expires_on is None
    # скоропорт: 7003 — дата со временем
    m = parse_mark(code("XyZ123", "2610181430", short=True))
    assert m.expires_at == datetime(2026, 10, 18, 14, 30) and m.expires_on == date(2026, 10, 18)
    # сканер потерял разделители — серийный номер подбирается по длине
    m = parse_mark(code("5abcDE", "261020", gs=False))
    assert (m.serial, m.expires_on) == ("5abcDE", date(2026, 10, 20))
    # префикс символики и FNC1 как «è» у некоторых сканеров
    m = parse_mark("]d2" + code("5abcDE", "261020").replace(GS, "è"))
    assert m.expires_on == date(2026, 10, 20)
    # день 00 — последний день месяца
    assert parse_mark(code("5abcDE", "260200")).expires_on == date(2026, 2, 28)
    # обычный EAN-13 и мусор — не код маркировки
    assert parse_mark("4607084350150") is None
    assert parse_mark("hello world") is None


async def _product(client, h, barcode: str | None = None) -> int:
    body = {"category_name": "Молочные продукты", "name": "Кефир 2,5%", "brand_name": "Простоквашино",
            "base_variant": {"calories": 53, "proteins": 3, "fats": 2.5, "carbs": 4}}
    if barcode:
        body["barcode"] = barcode
    r = await client.post("/api/v1/products/with-category", json=body, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_parse_endpoint_finds_product_and_registered(client):
    h = await register_and_login(client, "mark1", "mark1@test.com")
    pid = await _product(client, h, "4607084350150")
    r = await client.post("/api/v1/stock/marks/parse", json={"code": code("5abcDE", "261020")}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() | {} == {"gtin": GTIN, "barcode": "4607084350150", "serial": "5abcDE",
                             "expires_on": "2026-10-20", "product_id": pid, "product_name": "Кефир 2,5%",
                             "already_registered": False}
    bad = await client.post("/api/v1/stock/marks/parse", json={"code": "4607084350150xx"}, headers=h)
    assert bad.status_code == 400


async def test_add_packs_groups_by_expiry_and_splits_price(client):
    h = await register_and_login(client, "mark2", "mark2@test.com")
    pid = await _product(client, h)           # штрихкода нет — возьмётся из кода маркировки
    packs = [{"code": code("aaaaa1", "261020")}, {"code": code("aaaaa2", "261020")},
             {"code": code("aaaaa3", "261024")}, {"expires_on": "2026-10-30"}]
    r = await client.post("/api/v1/stock/lots/packs", headers=h, json={
        "product_id": pid, "pack_amount": 930, "price": 400, "packs": packs})
    assert r.status_code == 201, r.text
    item = next(i for i in r.json() if i["product_id"] == pid)
    lots = sorted(item["lots"], key=lambda l: l["expires_on"])
    assert [(l["expires_on"], float(l["quantity"]), float(l["price"])) for l in lots] == [
        ("2026-10-20", 1860.0, 200.0), ("2026-10-24", 930.0, 100.0), ("2026-10-30", 930.0, 100.0)]
    assert float(item["remaining"]) == 3720.0
    # штрихкод товара запомнился по коду маркировки
    prods = (await client.get("/api/v1/products/", params={"q": "кефир"}, headers=h)).json()
    assert prods[0]["barcode"] == "4607084350150"
    # та же пачка второй раз — нельзя
    again = await client.post("/api/v1/stock/lots/packs", headers=h, json={
        "product_id": pid, "pack_amount": 930, "packs": [{"code": code("aaaaa1", "261020")}]})
    assert again.status_code == 409
    parsed = (await client.post("/api/v1/stock/marks/parse", json={"code": code("aaaaa1")}, headers=h)).json()
    assert parsed["already_registered"] is True
    # дубль внутри одного запроса — тоже
    dup = await client.post("/api/v1/stock/lots/packs", headers=h, json={
        "product_id": pid, "pack_amount": 930, "packs": [{"code": code("bbbbb1")}, {"code": code("bbbbb1")}]})
    assert dup.status_code == 409


async def test_code_of_other_product_refused(client):
    h = await register_and_login(client, "mark3", "mark3@test.com")
    pid = await _product(client, h, "4600000000017")
    r = await client.post("/api/v1/stock/lots/packs", headers=h, json={
        "product_id": pid, "pack_amount": 930, "packs": [{"code": code("ccccc1", "261020")}]})
    assert r.status_code == 400 and "другого товара" in r.json()["detail"]


async def test_split_existing_lot_by_packs(client):
    h = await register_and_login(client, "mark4", "mark4@test.com")
    pid = await _product(client, h, "4607084350150")
    r = await client.post("/api/v1/stock/lots", headers=h, json={
        "product_id": pid, "quantity": 2790, "price": 300, "purchased_on": day(-1)})
    lot = next(i for i in r.json() if i["product_id"] == pid)["lots"][0]
    # пачек больше, чем в партии, — ошибка
    too_many = await client.post(f"/api/v1/stock/lots/{lot['id']}/packs", headers=h, json={
        "pack_amount": 930, "packs": [{"expires_on": "2026-10-20"}] * 4})
    assert too_many.status_code == 400
    r = await client.post(f"/api/v1/stock/lots/{lot['id']}/packs", headers=h, json={
        "pack_amount": 930, "packs": [{"code": code("ddddd1", "261020")}, {"code": code("ddddd2", "261025")},
                                      {"code": code("ddddd3", "261025")}]})
    assert r.status_code == 200, r.text
    lots = sorted(next(i for i in r.json() if i["product_id"] == pid)["lots"], key=lambda l: l["expires_on"])
    assert [(l["expires_on"], float(l["quantity"]), float(l["remaining"]), float(l["price"])) for l in lots] == [
        ("2026-10-20", 930.0, 930.0, 100.0), ("2026-10-25", 1860.0, 1860.0, 200.0)]
    assert {l["purchased_on"] for l in lots} == {day(-1)}
    # чужая партия — не найдена
    other = await register_and_login(client, "mark5", "mark5@test.com")
    nf = await client.post(f"/api/v1/stock/lots/{lot['id']}/packs", headers=other, json={
        "pack_amount": 930, "packs": [{"expires_on": "2026-10-20"}]})
    assert nf.status_code == 404
