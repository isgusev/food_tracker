"""Импорт кассовых чеков по QR (сервис code-qr.ru подменён — сети нет):
нормализация и размеры упаковок, подсказки (выученное → список → справочник),
ожидание ФНС, разнесение по списку и запасам, выученные соответствия."""
from __future__ import annotations


from decimal import Decimal

import pytest

from app.core.config import get_settings
from app.services import receipt_client
from app.services.receipt import (
    MATCH_THRESHOLD,
    is_non_food,
    match_text,
    normalize_receipt_name,
    parse_pack,
    parse_qr,
    product_score,
)
from tests.test_api import TODAY, register_and_login

pytestmark = pytest.mark.anyio

QR1 = "t=20261016T1923&s=1498.00&fn=9251440300007971&i=141637&fp=4087570038&n=1"
QR2 = "t=20261017T1000&s=103.66&fn=9251440300007971&i=141700&fp=1111111111&n=1"
INN = "7814148471"

ITEMS1 = [
    {"name": "Молоко СВЕЖЕЕ ЗАВТРА у/п пит 3,2% 500г", "quantity": 1, "price": 51.83, "sum": 51.83},
    {"name": "Лимоны  вес  1кг", "quantity": 0.416, "price": 80.69, "sum": 33.57},
    {"name": "Пакет ЛЕНТА средний майка 12кг", "quantity": 2, "price": 6.45, "sum": 12.90},
    {"name": "Кревет. королев. зам. 1кг", "quantity": 1, "price": 899.00, "sum": 899.00},
    {"name": "Шоколад ALPEN GOLD 85г", "quantity": 1, "price": 89.99, "sum": 89.99},
]
ITEMS2 = [
    {"name": "Молоко СВЕЖЕЕ ЗАВТРА у/п пит 3,2% 500г", "quantity": 2, "price": 51.83, "sum": 103.66},
]


def done(items, t="16.10.2026 19:23", s="1 498.00", inn=INN) -> dict:
    return {
        "success": True, "t": t, "fn": 9251440300007971, "i": 141637, "fp": 4087570038, "s": s,
        "status": "done", "error": "",
        "result": {"address": "СПб", "user": 'ООО "Лента"', "user_inn": inn, "items": items},
    }


class FakeProvider:
    """Подмена code-qr.ru: hash = QR, ответы info выдаются по очереди (последний повторяется)."""

    def __init__(self, monkeypatch):
        self.answers: dict[str, list[dict]] = {}
        self.info_calls = 0
        monkeypatch.setattr(receipt_client, "add_qr", self.add_qr)
        monkeypatch.setattr(receipt_client, "info", self.info)

    async def add_qr(self, qr: str) -> str:
        return qr

    async def info(self, receipt_hash: str) -> dict:
        self.info_calls += 1
        queue = self.answers[receipt_hash]
        return queue.pop(0) if len(queue) > 1 else queue[0]


async def mk_product(client, h, name, brand, category="Продукты") -> dict:
    r = await client.post("/api/v1/products/with-category", json={
        "category_name": category, "name": name, "brand_name": brand,
        "base_variant": {"manufacturer_name": brand, "calories": 50, "proteins": 3, "fats": 2, "carbs": 5},
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def list_with(client, h, *product_ids) -> dict:
    r = await client.post("/api/v1/shopping-lists", json={"start_date": TODAY, "end_date": TODAY}, headers=h)
    assert r.status_code == 200, r.text
    lst = r.json()
    for pid in product_ids:
        r = await client.post(f"/api/v1/shopping-lists/{lst['id']}/lines", json={"product_id": pid, "quantity": 500}, headers=h)
        assert r.status_code == 201, r.text
    return r.json()


# --- ЧИСТЫЕ ФУНКЦИИ ---


def test_normalize_and_abbreviations():
    assert normalize_receipt_name("Молоко СВЕЖЕЕ ЗАВТРА у/п пит 3,2% 500г") == "молоко свежее завтра питьевое 3,2% 500г"
    assert normalize_receipt_name("Мол.сгущ. цельное 8,5% ж/б 380г") == "молоко сгущенное цельное 8,5% 380г"
    assert normalize_receipt_name("Кревет. королев. зам. 1кг") == "креветки королев замороженные 1кг"
    assert normalize_receipt_name("Говяд. ВЫРЕЗКА охл. в/у") == "говядина вырезка охлажденная"
    assert normalize_receipt_name("Т/бумага ZEWA 4шт") == "туалетная бумага zewa 4шт"
    assert normalize_receipt_name("Ср-во д/посуды FAIRY 450мл") == "средство для посуды fairy 450мл"
    assert normalize_receipt_name("Ср-во д/пос. AOS") == "средство для посуды aos"
    assert normalize_receipt_name("Колбаса с/к Ёлкин   300г") == "колбаса сырокопченая елкин 300г"
    # для сравнения — без размеров и пометок, процент жирности остаётся
    assert match_text(normalize_receipt_name("Лимоны  вес  1кг")) == "лимоны"
    assert match_text(normalize_receipt_name("Молоко у/п пит 3,2% 500г")) == "молоко питьевое 3,2%"


def test_parse_pack_sizes_and_weighed_items():
    assert parse_pack("Молоко 3,2% 500г") == parse_pack("Молоко 3,2% 500 г")
    assert (parse_pack("Молоко 3,2% 500г").amount, parse_pack("Молоко 3,2% 500г").unit) == (Decimal("500"), "g")
    assert (parse_pack("Сок 930мл").amount, parse_pack("Сок 930мл").unit) == (Decimal("930"), "ml")
    assert (parse_pack("Вода 1,5л").amount, parse_pack("Вода 1,5л").unit) == (Decimal("1500"), "ml")
    assert (parse_pack("Сахар 1кг").amount, parse_pack("Сахар 1кг").unit) == (Decimal("1000"), "g")
    assert (parse_pack("Яйцо С1 10шт").amount, parse_pack("Яйцо С1 10шт").unit) == (Decimal("10"), "pcs")
    # несколько размеров — берём последний (вес всей пачки)
    assert parse_pack("Чай GREENFIELD 62,5г*8пак 500г").amount == Decimal("500")
    # весовой: «1кг» — цена за кило, количество в чеке — килограммы
    lemons = parse_pack("Лимоны  вес  1кг", Decimal("0.416"))
    assert lemons.weighed and lemons.amount == Decimal("1000") and lemons.unit == "g"
    assert parse_pack("Бананы", Decimal("1.25")).weighed           # дробное количество без «вес»
    assert parse_pack("Хлеб бородинский").amount is None


def test_non_food_and_qr_fields():
    assert is_non_food("Пакет ЛЕНТА средний майка 12кг")
    assert is_non_food("Салфетки бумажные 100шт") and is_non_food("Т/бумага ZEWA 4шт")
    assert is_non_food("Ср-во д/посуды FAIRY 450мл") and is_non_food("Губка для посуды 5шт")
    assert not is_non_food("Жев.резинка ORBIT 13,6г")              # жвачка — еда
    assert not is_non_food("Чай GREENFIELD 25пак")                 # пакетики чая — не пакет
    assert not is_non_food("Молоко 3,2% 500г")
    f = parse_qr(QR1)
    assert f["t"] == "20261016T1923" and f["s"] == "1498.00"
    assert parse_qr("https://check.example/?" + QR1)["fn"] == "9251440300007971"


def test_score_threshold():
    class P:  # минимальный «продукт» для оценки
        def __init__(self, name, brand=None):
            self.name, self.brand = name, (type("B", (), {"name": brand})() if brand else None)

    text = match_text(normalize_receipt_name("Молоко СВЕЖЕЕ ЗАВТРА у/п пит 3,2% 500г"))
    assert product_score(P("Молоко 3,2%"), text) == 1.0
    assert product_score(P("Молоко сгущенное"), text) < MATCH_THRESHOLD   # половина слов — мало
    assert product_score(P("Молоко сгущенное", "Свежее завтра"), text) < MATCH_THRESHOLD  # бренд — лишь прибавка
    shrimp = match_text(normalize_receipt_name("Кревет. королев. зам. 1кг"))
    assert product_score(P("Креветки королевские"), shrimp) >= MATCH_THRESHOLD   # обрезанное слово
    assert product_score(P("Сыр"), shrimp) < MATCH_THRESHOLD


# --- API ---


async def test_receipt_flow_list_catalog_alias(client, monkeypatch):
    h = await register_and_login(client, "rcpt", "rcpt@test.com")
    fake = FakeProvider(monkeypatch)
    milk = await mk_product(client, h, "Молоко 3,2%", "Свежее завтра", "Молочные продукты")
    lemon = await mk_product(client, h, "Лимон", "Без бренда", "Фрукты")
    shrimp = await mk_product(client, h, "Креветки королевские", "Агама", "Морепродукты")
    await mk_product(client, h, "Сыр", "Ламбер", "Молочные продукты")
    lst = await list_with(client, h, milk["id"], shrimp["id"])
    line_of = {x["product_id"]: x["id"] for x in lst["lines"]}

    # ФНС ещё не знает чек: сохраняем и ждём
    fake.answers[QR1] = [{"success": True, "status": "wait"}, done(ITEMS1)]
    r = await client.post("/api/v1/receipts", json={"qr": QR1}, headers=h)
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["status"] == "pending" and rec["items"] == []
    assert rec["purchased_at"].startswith("2026-10-16T19:23") and rec["total"] == "1498.00"   # из самого QR
    # повторный скан — тот же чек
    assert (await client.post("/api/v1/receipts", json={"qr": QR1}, headers=h)).json()["id"] == rec["id"]

    r = await client.get(f"/api/v1/receipts/{rec['id']}", headers=h)
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["status"] == "done" and rec["store_name"] == 'ООО "Лента"' and rec["store_inn"] == INN
    assert rec["total"] == "1498.00"
    s = [i["suggestion"] for i in rec["items"]]
    assert (s[0]["action"], s[0]["source"], s[0]["shopping_line_id"]) == ("list", "list", line_of[milk["id"]])
    assert s[0]["confidence"] >= MATCH_THRESHOLD and float(s[0]["quantity"]) == 500
    assert (s[1]["action"], s[1]["source"], s[1]["product_id"]) == ("extra", "catalog", lemon["id"])
    assert float(s[1]["quantity"]) == 416                                  # 0,416 кг
    assert (s[2]["action"], s[2]["source"]) == ("skip", "none")              # пакет
    assert (s[3]["action"], s[3]["shopping_line_id"]) == ("list", line_of[shrimp["id"]])
    assert float(s[3]["quantity"]) == 1000
    assert (s[4]["action"], s[4]["source"]) == ("skip", "none")              # шоколада нет в справочнике

    # чужая семья чек не видит
    other = await register_and_login(client, "rcpt_o", "rcpt_o@test.com")
    assert (await client.get(f"/api/v1/receipts/{rec['id']}", headers=other)).status_code == 404

    # разнесли: креветок на самом деле 800 г (поправили количество)
    lines = [
        {"index": 0, "action": "list", "shopping_line_id": s[0]["shopping_line_id"]},
        {"index": 1, "action": "extra", "product_id": lemon["id"]},
        {"index": 2, "action": "skip"},
        {"index": 3, "action": "list", "shopping_line_id": s[3]["shopping_line_id"], "quantity": 800},
    ]
    r = await client.post(f"/api/v1/receipts/{rec['id']}/apply", json={"lines": lines}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "applied" and r.json()["applied_at"]

    stock = {i["product_id"]: i for i in (await client.get("/api/v1/stock", headers=h)).json()}
    [milk_lot] = stock[milk["id"]]["lots"]
    assert float(milk_lot["quantity"]) == 500 and float(milk_lot["price"]) == 51.83
    assert milk_lot["purchased_on"] == "2026-10-16" and milk_lot["source"] == "purchase"   # дата чека
    [lemon_lot] = stock[lemon["id"]]["lots"]
    assert float(lemon_lot["quantity"]) == 416 and float(lemon_lot["price"]) == 33.57
    assert float(stock[shrimp["id"]]["lots"][0]["quantity"]) == 800

    active = (await client.get("/api/v1/shopping-lists/active", headers=h)).json()
    by_product = {x["product_id"]: x for x in active["lines"]}
    assert by_product[milk["id"]]["is_checked"] and by_product[shrimp["id"]]["is_checked"]
    assert by_product[lemon["id"]]["is_extra"] and by_product[lemon["id"]]["is_checked"]   # «вне плана»

    # второй раз — нельзя
    r = await client.post(f"/api/v1/receipts/{rec['id']}/apply", json={"lines": lines}, headers=h)
    assert r.status_code == 409

    # второй чек того же магазина: молоко узнаётся по выученному, ×2 упаковки
    fake.answers[QR2] = [done(ITEMS2, t="17.10.2026 10:00", s="103.66")]
    rec2 = (await client.post("/api/v1/receipts", json={"qr": QR2}, headers=h)).json()
    [item] = rec2["items"]
    sg = item["suggestion"]
    assert (sg["source"], sg["confidence"], sg["product_id"]) == ("alias", 1.0, milk["id"])
    assert sg["action"] == "extra" and float(sg["quantity"]) == 1000      # строка списка уже куплена

    # тот же товар в другом магазине — тоже узнаём, но чуть менее уверенно
    fake.answers["other-store"] = [done(ITEMS2, inn="7700000000")]
    sg = (await client.post("/api/v1/receipts", json={"qr": "other-store"}, headers=h)).json()["items"][0]["suggestion"]
    assert (sg["source"], sg["confidence"]) == ("alias", 0.9)

    recent = (await client.get("/api/v1/receipts", headers=h)).json()
    assert [x["status"] for x in recent] == ["done", "done", "applied"] and recent[2]["items_count"] == 5


async def test_apply_validation(client, monkeypatch):
    h = await register_and_login(client, "rval", "rval@test.com")
    fake = FakeProvider(monkeypatch)
    milk = await mk_product(client, h, "Молоко 3,2%", "Свежее завтра")
    fake.answers[QR1] = [{"success": True, "status": "process"}]
    rec = (await client.post("/api/v1/receipts", json={"qr": QR1}, headers=h)).json()
    r = await client.post(f"/api/v1/receipts/{rec['id']}/apply", json={"lines": []}, headers=h)
    assert r.status_code == 400 and "ФНС" in r.json()["detail"]

    fake.answers[QR1] = [done(ITEMS1)]
    bad = [
        [{"index": 99, "action": "skip"}],
        [{"index": 0, "action": "skip"}, {"index": 0, "action": "skip"}],
        [{"index": 0, "action": "list"}],                                     # без строки списка
        [{"index": 0, "action": "extra"}],                                    # без продукта
        [{"index": 4, "action": "extra", "product_id": milk["id"], "quantity": 0}],
    ]
    for lines in bad:
        r = await client.post(f"/api/v1/receipts/{rec['id']}/apply", json={"lines": lines}, headers=h)
        assert r.status_code in (400, 422), (lines, r.text)
    # ошибка в середине — ничего не применилось (одна транзакция)
    r = await client.post(f"/api/v1/receipts/{rec['id']}/apply", json={"lines": [
        {"index": 0, "action": "extra", "product_id": milk["id"]},
        {"index": 1, "action": "list", "shopping_line_id": 999999},
    ]}, headers=h)
    assert r.status_code == 404
    assert (await client.get("/api/v1/stock", headers=h)).json() == []
    assert (await client.get(f"/api/v1/receipts/{rec['id']}", headers=h)).json()["status"] == "done"


async def test_provider_error_then_retry(client, monkeypatch):
    h = await register_and_login(client, "rerr", "rerr@test.com")
    fake = FakeProvider(monkeypatch)
    fake.answers[QR1] = [{"success": False, "message": "Чек не найден"}]
    rec = (await client.post("/api/v1/receipts", json={"qr": QR1}, headers=h)).json()
    assert rec["status"] == "error" and rec["error"] == "Чек не найден"
    # позже ФНС узнала чек — повторный скан того же QR пробует заново
    fake.answers[QR1] = [done(ITEMS2)]
    again = (await client.post("/api/v1/receipts", json={"qr": QR1}, headers=h)).json()
    assert again["id"] == rec["id"] and again["status"] == "done" and len(again["items"]) == 1


async def test_missing_key_is_clear_error(client, monkeypatch):
    h = await register_and_login(client, "rkey", "rkey@test.com")
    monkeypatch.setattr(get_settings(), "codeqr_api_key", None)
    r = await client.post("/api/v1/receipts", json={"qr": QR1}, headers=h)
    assert r.status_code == 503
    assert r.json()["detail"] == "Импорт чеков не настроен: нет ключа CODEQR_API_KEY"
    assert (await client.get("/api/v1/receipts", headers=h)).json() == []


async def test_client_sends_key_header_and_passes_service_message(client, monkeypatch):
    """Настоящий клиент поверх подменённого транспорта: ключ — в заголовке «key»,
    success=false (HTTP 200) — понятная ошибка с сообщением сервиса, чек не сохраняется."""
    import httpx

    h = await register_and_login(client, "rmsg", "rmsg@test.com")
    monkeypatch.setattr(get_settings(), "codeqr_api_key", "test-key")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": False, "message": "Нет активного пакета доступа к API проверки чеков"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        receipt_client.httpx, "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    real_qr = "  t=20261015T2145&s=100.63&fn=7380440903750419&i=8489&fp=52085185&n=1 \n"
    r = await client.post("/api/v1/receipts", json={"qr": real_qr}, headers=h)
    assert r.status_code == 400
    assert r.json()["detail"] == "Сервис чеков: Нет активного пакета доступа к API проверки чеков"
    [req] = seen
    assert req.headers["key"] == "test-key" and "authorization" not in req.headers
    assert req.url.path == "/api/receipt/add-qr"
    assert req.content.startswith(b"qr=t%3D20261015T2145") and req.content.endswith(b"n%3D1")  # пробелы обрезаны
    assert (await client.get("/api/v1/receipts", headers=h)).json() == []


def test_qr_as_string_or_url():
    real = "t=20261015T2145&s=100.63&fn=7380440903750419&i=8489&fp=52085185&n=1"
    for qr in (real, f"  {real}\n", f"https://check.example/receipt?{real}"):
        f = parse_qr(qr)
        assert (f["t"], f["s"], f["fn"], f["fp"]) == ("20261015T2145", "100.63", "7380440903750419", "52085185")
