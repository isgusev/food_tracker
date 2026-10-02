import requests

BASE_URL = "http://127.0.0.1:8000/api"

TEST_PRODUCTS = [
    {
        "name": "Куриное филе", "brand": "Мираторг", "manufacturer": "Завод Мираторг",
        "category": "Мясо", "calories": 110, "proteins": 23.0, "fats": 1.9, "carbs": 0.0
    },
    {
        "name": "Куриное филе", "brand": "Петелинка", "manufacturer": "Петелинская фабрика",
        "category": "Мясо", "calories": 113, "proteins": 21.5, "fats": 2.5, "carbs": 0.0
    },
    {
        "name": "Молоко 3.2%", "brand": "Домик в деревне", "manufacturer": "Вимм-Билль-Данн",
        "category": "Молочные продукты", "calories": 60, "proteins": 3.0, "fats": 3.2, "carbs": 4.7
    },
    {
        "name": "Молоко 2.5%", "brand": "Простоквашино", "manufacturer": "Данон",
        "category": "Молочные продукты", "calories": 53, "proteins": 3.0, "fats": 2.5, "carbs": 4.7
    },
    {
        "name": "Творог 5%", "brand": "Савушкин", "manufacturer": "Савушкин Продукт",
        "category": "Молочные продукты", "calories": 107, "proteins": 12.0, "fats": 5.0, "carbs": 3.5
    },
    {
        "name": "Творог 9%", "brand": "Б.Ю. Александров", "manufacturer": "Ростагрокомплекс",
        "category": "Молочные продукты", "calories": 157, "proteins": 16.0, "fats": 9.0, "carbs": 3.0
    },
    {
        "name": "Крупа Гречневая", "brand": "Мистраль", "manufacturer": "Мистраль Трейдинг",
        "category": "Бакалея", "calories": 310, "proteins": 12.6, "fats": 2.6, "carbs": 68.0
    },
    {
        "name": "Крупа Гречневая", "brand": "Увелка", "manufacturer": "Ресурс ООО",
        "category": "Бакалея", "calories": 320, "proteins": 12.0, "fats": 2.0, "carbs": 67.0
    },
    {
        "name": "Макароны Перья", "brand": "Barilla", "manufacturer": "Барилла Рус",
        "category": "Бакалея", "calories": 359, "proteins": 14.0, "fats": 2.0, "carbs": 69.7
    },
    {
        "name": "Яйцо куриное C0", "brand": "Волжанин", "manufacturer": "Птицефабрика Волжанин",
        "category": "Яйца", "calories": 157, "proteins": 12.7, "fats": 11.5, "carbs": 0.7
    },
    {
        "name": "Овсяные хлопья", "brand": "Ясно Солнышко", "manufacturer": "Петербургский мельничный комбинат",
        "category": "Бакалея", "calories": 310, "proteins": 12.0, "fats": 6.0, "carbs": 51.0
    },
    {
        "name": "Масло оливковое", "brand": "Borges", "manufacturer": "Borges Branded Foods",
        "category": "Масла и жиры", "calories": 898, "proteins": 0.0, "fats": 99.8, "carbs": 0.0
    },
    {
        "name": "Рис Басмати", "brand": "Мистраль", "manufacturer": "Мистраль Трейдинг",
        "category": "Бакалея", "calories": 340, "proteins": 7.5, "fats": 0.5, "carbs": 78.0
    },
    {
        "name": "Рис Басмати", "brand": "Националь", "manufacturer": "Агро-Альянс",
        "category": "Бакалея", "calories": 350, "proteins": 7.0, "fats": 0.4, "carbs": 79.0
    },
    {
        "name": "Сливки 20%", "brand": "Домик в деревне", "manufacturer": "Вимм-Билль-Данн",
        "category": "Молочные продукты", "calories": 207, "proteins": 2.5, "fats": 20.0, "carbs": 4.0
    },
    {
        "name": "Сливки 20%", "brand": "Петропавловское", "manufacturer": "Молвест",
        "category": "Молочные продукты", "calories": 205, "proteins": 2.6, "fats": 20.0, "carbs": 3.8
    },
    {
        "name": "Фарш говяжий", "brand": "Мираторг", "manufacturer": "СК Короча",
        "category": "Мясо", "calories": 250, "proteins": 16.0, "fats": 20.0, "carbs": 0.0
    },
    {
        "name": "Фарш говяжий", "brand": "Самсон", "manufacturer": "Мясокомбинат Всеволожский",
        "category": "Мясо", "calories": 230, "proteins": 17.0, "fats": 18.0, "carbs": 0.0
    },
    {
        "name": "Стейк лосося", "brand": "Инара", "manufacturer": "Русская Рыбная Компания",
        "category": "Рыба и морепродукты", "calories": 142, "proteins": 19.8, "fats": 6.3, "carbs": 0.0
    },
    {
        "name": "Филе индейки", "brand": "Индилайт", "manufacturer": "Дамате",
        "category": "Мясо", "calories": 84, "proteins": 19.2, "fats": 0.7, "carbs": 0.0
    },
    {
        "name": "Томаты протертые", "brand": "Mutti", "manufacturer": "Mutti S.p.A.",
        "category": "Консервы", "calories": 26, "proteins": 1.2, "fats": 0.2, "carbs": 4.5
    },
    {
        "name": "Томаты протертые", "brand": "Помидорка", "manufacturer": "Экопродукт",
        "category": "Консервы", "calories": 22, "proteins": 1.1, "fats": 0.0, "carbs": 4.2
    },
    {
        "name": "Картофель свежий", "brand": "Без бренда", "manufacturer": "Агрохолдинг Выборжец",
        "category": "Овощи", "calories": 77, "proteins": 2.0, "fats": 0.4, "carbs": 16.3
    },
    {
        "name": "Шампиньоны свежие", "brand": "Грибная радуга", "manufacturer": "Посейдон ООО",
        "category": "Грибы", "calories": 27, "proteins": 4.3, "fats": 1.0, "carbs": 0.1
    },
    {
        "name": "Лук репчатый", "brand": "Без бренда", "manufacturer": "Фосагро",
        "category": "Овощи", "calories": 41, "proteins": 1.4, "fats": 0.2, "carbs": 8.2
    },
    {
        "name": "Сыр Моцарелла", "brand": "Unagrande", "manufacturer": "Умалат",
        "category": "Сыры", "calories": 247, "proteins": 18.5, "fats": 19.0, "carbs": 0.5
    },
    {
        "name": "Сыр Моцарелла", "brand": "Galbani", "manufacturer": " Lactalis",
        "category": "Сыры", "calories": 238, "proteins": 18.0, "fats": 18.0, "carbs": 1.0
    },
    {
        "name": "Сыр Пармезан", "brand": "Dolce Granto", "manufacturer": "Нева Милк",
        "category": "Сыры", "calories": 392, "proteins": 33.0, "fats": 28.0, "carbs": 0.0
    },
    {
        "name": "Масло сливочное 82.5%", "brand": "Брест-Литовск", "manufacturer": "Савушкин Продукт",
        "category": "Масла и жиры", "calories": 748, "proteins": 0.6, "fats": 82.5, "carbs": 0.8
    },
    {
        "name": "Соус Соевый", "brand": "Kikkoman", "manufacturer": "Kikkoman Б.В.",
        "category": "Соусы", "calories": 57, "proteins": 10.0, "fats": 0.0, "carbs": 3.2
    },
    {
        "name": "Соус Соевый", "brand": "Сен Сой", "manufacturer": "Состра",
        "category": "Соусы", "calories": 51, "proteins": 3.5, "fats": 0.0, "carbs": 11.0
    },
    {
        "name": "Паста Томатная", "brand": "Кухмастер", "manufacturer": "Кухмастер ООО",
        "category": "Соусы", "calories": 68, "proteins": 4.0, "fats": 0.0, "carbs": 15.8
    }
]

def get_or_create_categories():
    print("📋 Синхронизация категорий...")
    try:
        res = requests.get(f"{BASE_URL}/categories/")
        existing = {c['name'].lower(): c['id'] for c in res.json()} if res.status_code == 200 else {}
    except:
        existing = {}
        
    category_map = {}
    unique_names = set(item['category'] for item in TEST_PRODUCTS)
    
    for c_name in unique_names:
        c_name_lower = c_name.lower()
        if c_name_lower in existing:
            category_map[c_name] = existing[c_name_lower]
        else:
            c_res = requests.post(f"{BASE_URL}/categories/", json={"name": c_name})
            if c_res.status_code in [200, 201]:
                category_map[c_name] = c_res.json()['id']
                print(f"   -> Создана новая категория: {c_name}")
            else:
                # Альтернативный путь роутера
                c_res_alt = requests.post(f"{BASE_URL}/products/categories/", json={"name": c_name})
                if c_res_alt.status_code in [200, 201]:
                    category_map[c_name] = c_res_alt.json()['id']
                    print(f"   -> Создана новая категория: {c_name}")
                else:
                    category_map[c_name] = 1
                    
    return category_map

def seed_database():
    print("🚀 Запуск точной заливки продуктов по логике вашего бэкенда...")
    category_map = get_or_create_categories()
    success_count = 0
    
    for item in TEST_PRODUCTS:
        cat_id = category_map.get(item['category'], 1)
        
        # Строим ИДEАЛЬНЫЙ payload, в точности как требует ваш schemas.ProductCreate
        product_payload = {
            "name": item['name'],
            "category_id": cat_id,
            "brand_name": item['brand'],  # На самом верхнем уровне!
            "base_variant": {             # Вложенный объект для производителя и КБЖУ
                "manufacturer_name": item['manufacturer'],
                "calories": item['calories'],
                "proteins": item['proteins'],
                "fats": item['fats'],
                "carbs": item['carbs']
            }
        }
        
        p_res = requests.post(f"{BASE_URL}/products/", json=product_payload)
        
        if p_res.status_code in [200, 201]:
            print(f"✅ Продукт создан: {item['name']} ({item['brand']} / {item['manufacturer']})")
            success_count += 1
        elif p_res.status_code == 400 and "уже существует" in p_res.text:
            print(f"ℹ️ Продукт уже есть в базе: {item['name']} ({item['brand']})")
            success_count += 1
        else:
            print(f"❌ Ошибка создания для {item['name']}: {p_res.status_code} -> {p_res.text}")

    print(f"\n🎉 Заливка завершена! Успешно обработано продуктов: {success_count} из {len(TEST_PRODUCTS)}")

if __name__ == "__main__":
    seed_database()