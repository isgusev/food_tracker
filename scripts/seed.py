"""Заполнение демо-данными через публичное API (с аутентификацией).

Скрипт:
  1. Регистрирует (или логинит) demo-пользователя и получает JWT.
  2. Создает справочник продуктов (категории → бренды → производители → версии КБЖУ).
  3. Создает пару рецептов и дневную запись, чтобы UI/API сразу были «живыми».

Использование (запущенный сервер обязателен):
    python -m scripts.seed                       # localhost:8000, пользователь demo
    python -m scripts.seed --url http://host:port --user ivan --password ***
Продукты идемпотентны: дубликаты (400 "уже существует") молча пропускаются.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

import requests

# --- Демо-каталог: (название, бренд, производитель, категория, ккалу, б, ж, у) ---
PRODUCTS: list[dict] = [
    {"name": "Куриное филе", "brand": "Мираторг", "manufacturer": "Завод Мираторг", "category": "Мясо", "calories": 110, "proteins": 23.0, "fats": 1.9, "carbs": 0.0},
    {"name": "Куриное филе", "brand": "Петелинка", "manufacturer": "Петелинская фабрика", "category": "Мясо", "calories": 113, "proteins": 21.5, "fats": 2.5, "carbs": 0.0},
    {"name": "Молоко 3.2%", "brand": "Домик в деревне", "manufacturer": "Вимм-Билль-Данн", "category": "Молочные продукты", "calories": 60, "proteins": 3.0, "fats": 3.2, "carbs": 4.7},
    {"name": "Творог 5%", "brand": "Савушкин", "manufacturer": "Савушкин Продукт", "category": "Молочные продукты", "calories": 107, "proteins": 12.0, "fats": 5.0, "carbs": 3.5},
    {"name": "Крупа Гречневая", "brand": "Мистраль", "manufacturer": "Мистраль Трейдинг", "category": "Бакалея", "calories": 310, "proteins": 12.6, "fats": 2.6, "carbs": 68.0},
    {"name": "Крупа Гречневая", "brand": "Увелка", "manufacturer": "Ресурс ООО", "category": "Бакалея", "calories": 320, "proteins": 12.0, "fats": 2.0, "carbs": 67.0},
    {"name": "Макароны Перья", "brand": "Barilla", "manufacturer": "Барилла Рус", "category": "Бакалея", "calories": 359, "proteins": 14.0, "fats": 2.0, "carbs": 69.7},
    {"name": "Яйцо куриное C0", "brand": "Волжанин", "manufacturer": "Птицефабрика Волжанин", "category": "Яйца", "calories": 157, "proteins": 12.7, "fats": 11.5, "carbs": 0.7},
    {"name": "Овсяные хлопья", "brand": "Ясно Солнышко", "manufacturer": "Петербургский мельничный комбинат", "category": "Бакалея", "calories": 310, "proteins": 12.0, "fats": 6.0, "carbs": 51.0},
    {"name": "Масло оливковое", "brand": "Borges", "manufacturer": "Borges Branded Foods", "category": "Масла и жиры", "calories": 898, "proteins": 0.0, "fats": 99.8, "carbs": 0.0},
    {"name": "Рис Басмати", "brand": "Мистраль", "manufacturer": "Мистраль Трейдинг", "category": "Бакалея", "calories": 340, "proteins": 7.5, "fats": 0.5, "carbs": 78.0},
    {"name": "Сливки 20%", "brand": "Домик в деревне", "manufacturer": "Вимм-Билль-Данн", "category": "Молочные продукты", "calories": 207, "proteins": 2.5, "fats": 20.0, "carbs": 4.0},
    {"name": "Фарш говяжий", "brand": "Мираторг", "manufacturer": "СК Короча", "category": "Мясо", "calories": 250, "proteins": 16.0, "fats": 20.0, "carbs": 0.0},
    {"name": "Стейк лосося", "brand": "Инара", "manufacturer": "Русская Рыбная Компания", "category": "Рыба и морепродукты", "calories": 142, "proteins": 19.8, "fats": 6.3, "carbs": 0.0},
    {"name": "Филе индейки", "brand": "Индилайт", "manufacturer": "Дамате", "category": "Мясо", "calories": 84, "proteins": 19.2, "fats": 0.7, "carbs": 0.0},
    {"name": "Томаты протертые", "brand": "Mutti", "manufacturer": "Mutti S.p.A.", "category": "Консервы", "calories": 26, "proteins": 1.2, "fats": 0.2, "carbs": 4.5},
    {"name": "Картофель свежий", "brand": "Без бренда", "manufacturer": "Агрохолдинг Выборжец", "category": "Овощи", "calories": 77, "proteins": 2.0, "fats": 0.4, "carbs": 16.3},
    {"name": "Шампиньоны свежие", "brand": "Грибная радуга", "manufacturer": "Посейдон ООО", "category": "Грибы", "calories": 27, "proteins": 4.3, "fats": 1.0, "carbs": 0.1},
    {"name": "Лук репчатый", "brand": "Без бренда", "manufacturer": "Фосагро", "category": "Овощи", "calories": 41, "proteins": 1.4, "fats": 0.2, "carbs": 8.2},
    {"name": "Сыр Моцарелла", "brand": "Unagrande", "manufacturer": "Умалат", "category": "Сыры", "calories": 247, "proteins": 18.5, "fats": 19.0, "carbs": 0.5},
    {"name": "Сыр Пармезан", "brand": "Dolce Granto", "manufacturer": "Нева Милк", "category": "Сыры", "calories": 392, "proteins": 33.0, "fats": 28.0, "carbs": 0.0},
    {"name": "Масло сливочное 82.5%", "brand": "Брест-Литовск", "manufacturer": "Савушкин Продукт", "category": "Масла и жиры", "calories": 748, "proteins": 0.6, "fats": 82.5, "carbs": 0.8},
    {"name": "Соус Соевый", "brand": "Kikkoman", "manufacturer": "Kikkoman Б.В.", "category": "Соусы", "calories": 57, "proteins": 10.0, "fats": 0.0, "carbs": 3.2},
    {"name": "Паста Томатная", "brand": "Кухмастер", "manufacturer": "Кухмастер ООО", "category": "Соусы", "calories": 68, "proteins": 4.0, "fats": 0.0, "carbs": 15.8},
]


class Api:
    """Тонкая обертка над HTTP-клиентом с JWT."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/") + "/api/v1"
        self.session = requests.Session()

    # ---------- auth ----------
    def login(self, username: str, password: str) -> bool:
        r = self.session.post(f"{self.base}/auth/login", data={"identifier": username, "password": password})
        if r.status_code != 200:
            return False
        self.session.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return True

    def register(self, username: str, email: str, password: str) -> None:
        r = self.session.post(
            f"{self.base}/auth/register",
            json={"username": username, "email": email, "password": password},
        )
        if r.status_code not in (201, 400, 409):  # 400/409 — уже зарегистрирован
            r.raise_for_status()

    # ---------- helpers ----------
    @staticmethod
    def _ok(r: requests.Response) -> bool:
        return r.status_code in (200, 201)

    @staticmethod
    def _is_duplicate(r: requests.Response) -> bool:
        return r.status_code in (400, 409) and "существует" in r.text.lower()

    # ---------- catalog ----------
    def get_or_create_category(self, name: str) -> int:
        r = self.session.get(f"{self.base}/products/categories")
        r.raise_for_status()
        for c in r.json():
            if c["name"].lower() == name.lower():
                return c["id"]
        r = self.session.post(f"{self.base}/products/categories", json={"name": name})
        if not self._ok(r):
            r.raise_for_status()
        return r.json()["id"]

    def create_product(self, category_id: int, item: dict) -> int | None:
        payload = {
            "category_id": category_id,
            "name": item["name"],
            "brand_name": item["brand"],
            "base_variant": {
                "manufacturer_name": item["manufacturer"],
                "calories": item["calories"],
                "proteins": item["proteins"],
                "fats": item["fats"],
                "carbs": item["carbs"],
            },
        }
        r = self.session.post(f"{self.base}/products/", json=payload)
        if self._ok(r):
            return r.json()["id"]
        if self._is_duplicate(r):
            return None  # уже есть — идемпотентно пропускаем
        print(f"  ❌ {item['name']} ({item['brand']}): {r.status_code} {r.text[:200]}")
        return None

    def find_variant_by_manufacturer(self, product_name: str, brand: str, manufacturer: str) -> int | None:
        """Находит активную версию КБЖУ нужного производителя через список продуктов."""
        r = self.session.get(f"{self.base}/products/", params={"limit": 500})
        r.raise_for_status()
        for p in r.json():
            if p["name"] != product_name:
                continue
            if (p.get("brand") or {}).get("name") != brand:
                continue
            for m in p.get("manufacturers") or []:
                if m.get("name") == manufacturer:
                    variants = [v for v in m.get("variants") or [] if v.get("is_active")]
                    if variants:
                        return variants[0]["id"]
        return None

    # ---------- recipes & diary ----------
    def get_or_create_recipe_category(self, name: str) -> int:
        r = self.session.get(f"{self.base}/recipes/categories")
        r.raise_for_status()
        for c in r.json():
            if c["name"].lower() == name.lower():
                return c["id"]
        r = self.session.post(f"{self.base}/recipes/categories", json={"name": name})
        if not self._ok(r):
            r.raise_for_status()
        return r.json()["id"]

    def get_or_create_recipe(self, cat_id: int, name: str, ingredients: list[dict], weight: float) -> int | None:
        """Возвращает id существующего рецепта с таким именем либо создает новый."""
        r = self.session.get(f"{self.base}/recipes/", params={"limit": 500})
        if self._ok(r):
            for rec in r.json():
                if rec["name"] == name:
                    return rec["id"]
        r = self.session.post(
            f"{self.base}/recipes/",
            json={
                "name": name,
                "recipe_category_id": cat_id,
                "estimated_cooked_weight": weight,
                "default_servings": 2,
                "ingredients": ingredients,
            },
        )
        if self._ok(r):
            return r.json()["id"]
        print(f"  ❌ рецепт {name}: {r.status_code} {r.text[:200]}")
        return None

    def add_diary_plan(self, recipe_id: int, weight_g: float) -> bool:
        today = date.today().isoformat()
        r = self.session.get(f"{self.base}/diary/day/{today}")
        if self._ok(r) and any(x["recipe_id"] == recipe_id for x in r.json()):
            return True  # план на сегодня уже есть — не дублируем
        r = self.session.post(
            f"{self.base}/diary/",
            json={
                "date_day": today,
                "meal_type": "dinner",
                "recipe_id": recipe_id,
                "weight_g": weight_g,
            },
        )
        if self._ok(r):
            return True
        print(f"  ⚠ план дня: {r.status_code} {r.text[:200]}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed демо-данных через API")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--user", default="demo")
    parser.add_argument("--email", default="demo@example.com")
    parser.add_argument("--password", default="demo-pass-123")
    args = parser.parse_args()

    api = Api(args.url)

    # 0. Проверка доступности сервера
    try:
        health = requests.get(args.url.rstrip("/") + "/health", timeout=5)
        health.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"❌ Сервер недоступен по адресу {args.url}: {exc}\n"
              f"   Запустите: uvicorn app.main:app --reload")
        return 1

    # 1. Пользователь
    print(f"👤 Пользователь '{args.user}'…")
    api.register(args.user, args.email, args.password)
    if not api.login(args.user, args.password):
        print("❌ Не удалось войти под demo-пользователем")
        return 1
    print("   ✅ авторизован (JWT получен)")

    # 2. Каталог продуктов
    print("🛒 Заливка каталога продуктов…")
    categories: dict[str, int] = {}
    created = skipped = 0
    for item in PRODUCTS:
        cat = item["category"]
        if cat not in categories:
            categories[cat] = api.get_or_create_category(cat)
        if api.create_product(categories[cat], item) is not None:
            created += 1
        else:
            skipped += 1
    print(f"   ✅ создано: {created}, пропущено (дубликаты): {skipped}")

    # 3. Рецепты из реально существующих вариантов КБЖУ
    print("🍳 Демо-рецепты…")
    rc_cat = api.get_or_create_recipe_category("Основные блюда")
    buckwheat_v = api.find_variant_by_manufacturer("Крупа Гречневая", "Мистраль", "Мистраль Трейдинг")
    chicken_v = api.find_variant_by_manufacturer("Куриное филе", "Мираторг", "Завод Мираторг")
    oil_v = api.find_variant_by_manufacturer("Масло оливковое", "Borges", "Borges Branded Foods")
    mushroom_v = api.find_variant_by_manufacturer("Шампиньоны свежие", "Грибная радуга", "Посейдон ООО")

    if buckwheat_v and chicken_v:
        rid = api.get_or_create_recipe(
            rc_cat, "Гречка с курицей",
            [{"variant_id": buckwheat_v, "weight_g": 200}, {"variant_id": chicken_v, "weight_g": 400}],
            weight=550.0,
        )
        if rid:
            print(f"   ✅ рецепт 'Гречка с курицей' (id={rid})")
            api.add_diary_plan(rid, 300.0)
    if mushroom_v and oil_v:
        rid2 = api.get_or_create_recipe(
            rc_cat, "Жареные шампиньоны",
            [{"variant_id": mushroom_v, "weight_g": 300}, {"variant_id": oil_v, "weight_g": 10}],
            weight=280.0,
        )
        if rid2:
            print(f"   ✅ рецепт 'Жареные шампиньоны' (id={rid2})")

    print("\n🎉 Seed завершён. Откройте http://127.0.0.1:8000/docs и войдите через /api/v1/auth/login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
