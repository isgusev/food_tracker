"""Идемпотентный сидинг демо-данных через публичный API.

Запуск (при работающем сервере на http://127.0.0.1:8000):

    python -m scripts.seed [--url http://127.0.0.1:8000] [--user demo] [--password demo-pass-123]

Скрипт регистрирует демо-пользователя (или логинит существующего), затем
создаёт категории, продукты и базовые версии КБЖУ. Повторный запуск
безопасен: дубликаты распознаются по кодам 400/409 и пропускаются.
"""
from __future__ import annotations

import argparse
import sys

import requests

TEST_PRODUCTS = [
    {"name": "Куриное филе", "brand": "Мираторг", "manufacturer": "Завод Мираторг",
     "category": "Мясо", "calories": 110, "proteins": 23.0, "fats": 1.9, "carbs": 0.0},
    {"name": "Куриное филе", "brand": "Петелинка", "manufacturer": "Петелинская фабрика",
     "category": "Мясо", "calories": 113, "proteins": 21.5, "fats": 2.5, "carbs": 0.0},
    {"name": "Молоко 3.2%", "brand": "Домик в деревне", "manufacturer": "Вимм-Билль-Данн",
     "category": "Молочные продукты", "calories": 60, "proteins": 3.0, "fats": 3.2, "carbs": 4.7},
    {"name": "Молоко 2.5%", "brand": "Простоквашино", "manufacturer": "Данон",
     "category": "Молочные продукты", "calories": 53, "proteins": 3.0, "fats": 2.5, "carbs": 4.7},
    {"name": "Творог 5%", "brand": "Савушкин", "manufacturer": "Савушкин Продукт",
     "category": "Молочные продукты", "calories": 107, "proteins": 12.0, "fats": 5.0, "carbs": 3.5},
    {"name": "Творог 9%", "brand": "Б.Ю. Александров", "manufacturer": "Ростагрокомплекс",
     "category": "Молочные продукты", "calories": 157, "proteins": 16.0, "fats": 9.0, "carbs": 3.0},
    {"name": "Гречка сухая", "brand": "Увелка", "manufacturer": "Увелка ООО",
     "category": "Крупы", "calories": 343, "proteins": 12.6, "fats": 3.3, "carbs": 68.0},
    {"name": "Рис круглозерный", "brand": "Националь", "manufacturer": "Мистраль",
     "category": "Крупы", "calories": 344, "proteins": 6.7, "fats": 0.7, "carbs": 79.0},
    {"name": "Овсяные хлопья", "brand": "Геркулес", "manufacturer": "Хопероф",
     "category": "Крупы", "calories": 366, "proteins": 11.9, "fats": 7.2, "carbs": 69.4},
    {"name": "Яйцо куриное С1", "brand": "РОСКО", "manufacturer": "РОСКО птицефабрика",
     "category": "Яйца", "calories": 157, "proteins": 12.7, "fats": 11.5, "carbs": 0.7},
    {"name": "Банан", "brand": "Chiquita", "manufacturer": "Chiquita Brands",
     "category": "Фрукты", "calories": 96, "proteins": 1.5, "fats": 0.5, "carbs": 21.0},
    {"name": "Яблоко Гренни Смит", "brand": "Фермерское", "manufacturer": "Сады Кубани",
     "category": "Фрукты", "calories": 47, "proteins": 0.4, "fats": 0.4, "carbs": 9.8},
    {"name": "Апельсин", "brand": "ФрутоНяня", "manufacturer": "Levina",
     "category": "Фрукты", "calories": 43, "proteins": 0.9, "fats": 0.2, "carbs": 8.1},
    {"name": "Помидор", "brand": "Вкуснотеево", "manufacturer": "Теплицы Крыма",
     "category": "Овощи", "calories": 20, "proteins": 0.6, "fats": 0.2, "carbs": 4.2},
    {"name": "Огурец свежий", "brand": "Домик в деревне", "manufacturer": "Эко-ферма",
     "category": "Овощи", "calories": 15, "proteins": 0.8, "fats": 0.1, "carbs": 2.8},
    {"name": "Морковь", "brand": "365 дней", "manufacturer": "Агро-Альянс",
     "category": "Овощи", "calories": 32, "proteins": 1.3, "fats": 0.1, "carbs": 6.9},
    {"name": "Картофель молодой", "brand": "Есть!", "manufacturer": "Фасоль",
     "category": "Овощи", "calories": 77, "proteins": 2.0, "fats": 0.4, "carbs": 16.0},
    {"name": "Хлеб цельнозерновой", "brand": "Хлебников", "manufacturer": "Хлебников ООО",
     "category": "Хлеб", "calories": 244, "proteins": 8.6, "fats": 2.2, "carbs": 45.0},
    {"name": "Макароны рожки", "brand": "Barilla", "manufacturer": "Barilla G.e F.",
     "category": "Макаронные изделия", "calories": 354, "proteins": 12.0, "fats": 1.5, "carbs": 70.0},
    {"name": "Сыр Российский 45%", "brand": "Простоквашино", "manufacturer": "Данон",
     "category": "Сыры", "calories": 361, "proteins": 24.1, "fats": 29.5, "carbs": 0.3},
    {"name": "Масло сливочное 82.5%", "brand": "Крестьянское", "manufacturer": "Простоквашино",
     "category": "Масло", "calories": 748, "proteins": 0.5, "fats": 82.5, "carbs": 0.8},
    {"name": "Кетчуп томатный", "brand": "Красnodar", "manufacturer": "Юнимилк",
     "category": "Соусы", "calories": 91, "proteins": 1.5, "fats": 0.1, "carbs": 21.0},
    {"name": "Майонез Провансаль", "brand": "ТМ Махеевъ", "manufacturer": "Махеевъ",
     "category": "Соусы", "calories": 618, "proteins": 3.5, "fats": 67.0, "carbs": 2.6},
    {"name": "Соевый соус", "brand": "Kikkoman", "manufacturer": "Kikkoman",
     "category": "Соусы", "calories": 51, "proteins": 3.5, "fats": 0.0, "carbs": 11.0},
]


def _is_duplicate(resp: requests.Response) -> bool:
    """Дубликат определяется и по 400, и по 409 (API отдаёт Conflict)."""
    return resp.status_code in (400, 409) and "существует" in resp.text.lower()


class Seeder:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.api = f"{base_url.rstrip('/')}/api/v1"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.created = 0
        self.skipped = 0

    # ---------- аутентификация ----------
    def authenticate(self) -> None:
        reg = self.session.post(
            f"{self.api}/auth/register",
            json={
                "username": self.username,
                "email": f"{self.username}@example.com",
                "password": self.password,
            },
        )
        if reg.status_code == 201 or _is_duplicate(reg):
            # /auth/login принимает form-data (поля identifier + password)
            login = self.session.post(
                f"{self.api}/auth/login",
                data={"identifier": self.username, "password": self.password},
            )
            if login.status_code != 200:
                sys.exit(f"❌ Не удалось войти: {login.status_code} {login.text}")
            self.session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
            print(f"🔐 Аутентифицирован как '{self.username}'")
        else:
            sys.exit(f"❌ Регистрация не удалась: {reg.status_code} {reg.text}")

    # ---------- справочники ----------
    def sync_categories(self) -> dict[str, int]:
        resp = self.session.get(f"{self.api}/products/categories")
        if resp.status_code != 200:
            sys.exit(f"❌ Не удалось получить категории: {resp.status_code} {resp.text}")
        existing = {c["name"].lower(): c["id"] for c in resp.json()}

        result: dict[str, int] = {}
        for name in sorted({p["category"] for p in TEST_PRODUCTS}):
            if name.lower() in existing:
                result[name] = existing[name.lower()]
                continue
            created = self.session.post(f"{self.api}/products/categories", json={"name": name})
            if created.status_code == 201:
                result[name] = created.json()["id"]
                print(f"   + категория: {name}")
            elif _is_duplicate(created):
                again = self.session.get(f"{self.api}/products/categories").json()
                result[name] = next(c["id"] for c in again if c["name"].lower() == name.lower())
            else:
                sys.exit(f"❌ Категория '{name}': {created.status_code} {created.text}")
        return result

    # ---------- продукты ----------
    def seed_products(self, categories: dict[str, int]) -> None:
        for item in TEST_PRODUCTS:
            payload = {
                "name": item["name"],
                "category_id": categories[item["category"]],
                "brand_name": item["brand"],
                "base_variant": {
                    "manufacturer_name": item["manufacturer"],
                    "calories": item["calories"],
                    "proteins": item["proteins"],
                    "fats": item["fats"],
                    "carbs": item["carbs"],
                },
            }
            resp = self.session.post(f"{self.api}/products/", json=payload)
            if resp.status_code == 201:
                self.created += 1
                print(f"✅ Создан: {item['name']} ({item['brand']})")
            elif _is_duplicate(resp):
                self.skipped += 1
                print(f"ℹ️  Уже есть: {item['name']} ({item['brand']})")
            else:
                print(f"❌ Ошибка для {item['name']}: {resp.status_code} {resp.text}")

    def run(self) -> None:
        self.authenticate()
        categories = self.sync_categories()
        self.seed_products(categories)
        print(f"\n🎉 Готово! создано: {self.created}, пропущено (дубликаты): {self.skipped}, "
              f"всего в наборе: {len(TEST_PRODUCTS)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Заливка демо-данных через API")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="базовый адрес API")
    parser.add_argument("--user", default="demo", help="имя демо-пользователя")
    parser.add_argument("--password", default="demo-pass-123", help="пароль (мин. 8 символов)")
    args = parser.parse_args()
    Seeder(args.url, args.user, args.password).run()


if __name__ == "__main__":
    main()
