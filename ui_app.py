from __future__ import annotations

import streamlit as st
import requests
from datetime import date, timedelta
import pandas as pd

st.set_page_config(page_title="Food Tracker UI", layout="wide", initial_sidebar_state="expanded")

BASE_URL = "http://127.0.0.1:8000/api"
USER_ID = "ivan_culinar"

st.title("🍎 Личный Пищевой Трекер")

# Навигация (Добавили Список покупок)
menu = st.sidebar.radio(
    "Навигация",
    ["📅 Дневник питания", "🍲 Мой Холодильник", "📖 Книга рецептов", "🛒 Список покупок", "📦 Каталог продуктов"]
)

def get_all(endpoint):
    try:
        res = requests.get(f"{BASE_URL}/{endpoint}")
        return res.json() if res.status_code == 200 else []
    except:
        return []

# ==========================================
# ЭКРАН 1: ДНЕВНИК ПИТАНИЯ
# ==========================================
if menu == "📅 Дневник питания":
    st.header("📅 Дневник и План питания")
    
    selected_date = st.date_input("Выберите дату", date.today())
    date_str = selected_date.strftime("%Y-%m-%d")
    
    diary_entries = get_all(f"diary/{USER_ID}/{date_str}")
    
    total_cal = sum(float(e['calories']) for e in diary_entries)
    total_p = sum(float(e['proteins']) for e in diary_entries)
    total_f = sum(float(e['fats']) for e in diary_entries)
    total_c = sum(float(e['carbs']) for e in diary_entries)
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔥 Калории за день", f"{total_cal:.1f} ккал")
    col2.metric("🥩 Белки", f"{total_p:.1f} г")
    col3.metric("🥑 Жиры", f"{total_f:.1f} г")
    col4.metric("🍞 Углеводы", f"{total_c:.1f} г")
    
    st.markdown("---")
    
    meals = {"breakfast": "🌅 Завтрак", "lunch": "🏙️ Обед", "dinner": "🌆 Ужин", "snack": "🍏 Перекус"}
    
    for meal_key, meal_name in meals.items():
        st.subheader(meal_name)
        meal_entries = [e for e in diary_entries if e['meal_type'] == meal_key]
        
        if not meal_entries:
            st.caption("Ничего не запланировано")
        else:
            for entry in meal_entries:
                status_emoji = "📝" if entry['status'] == "template_plan" else "🎯" if entry['status'] == "cooked_plan" else "✅"
                status_text = "Примерный план" if entry['status'] == "template_plan" else "Точный план (в холодильнике)" if entry['status'] == "cooked_plan" else "СЪЕДЕНО (ФАКТ)"
                
                with st.expander(f"{status_emoji} {entry['recipe_name']} — {float(entry['weight_g']):.0f}г ({float(entry['calories']):.0f} ккал)"):
                    st.write(f"**Статус:** {status_text}")
                    st.write(f"**КБЖУ порции:** Б: {entry['proteins']} | Ж: {entry['fats']} | У: {entry['carbs']}")
                    
                    if entry['status'] != 'fact':
                        # Фактический вес вводим прямо перед тем, как съесть!
                        # По умолчанию подставляем туда плановый вес
                        fact_weight = st.number_input(
                            "Сколько грамм вы съели по факту?", 
                            min_value=10, max_value=2000, 
                            value=int(float(entry['weight_g'])),
                            key=f"fact_weight_{entry['id']}",
                            help="Сюда можно внести точный вес, если вы доели за кем-то или порция отличалась."
                        )
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            if st.button("✅ Съесть (Подтвердить факт)", key=f"btn_eat_{entry['id']}", type="primary"):
                                res = requests.patch(f"{BASE_URL}/diary/{entry['id']}/eat", json={"weight_g": fact_weight})
                                if res.status_code == 200: st.rerun()
                        with c2:
                            if st.button("🗑️ Удалить план", key=f"btn_del_{entry['id']}"):
                                res = requests.delete(f"{BASE_URL}/diary/{entry['id']}")
                                if res.status_code == 204: st.rerun()
                    else:
                        st.success("✨ Блюдо уже съедено. Вес списан из холодильника.")

	# Кнопка добавления нового плана с динамическим масштабированием на семью
        with st.popover(f"➕ Запланировать на {meal_name.lower()}"):
            recipes = get_all("recipes")
            cooking_logs = get_all("recipes/cooking-logs")
            
            # Собираем актуальные остатки готовой еды в холодильнике
            fridge_stocks = {}
            for log in cooking_logs:
                if not log['is_finished']:
                    fridge_stocks[log['recipe_id']] = fridge_stocks.get(log['recipe_id'], 0.0) + float(log['current_remaining_weight'])
            
            if not recipes:
                st.warning("Сначала добавьте рецепты в кулинарную книгу!")
            else:
                recipe_map = {r['name']: r for r in recipes}
                chosen_recipe_name = st.selectbox("Выберите рецепт", list(recipe_map.keys()), key=f"select_{meal_key}")
                
                selected_recipe = recipe_map[chosen_recipe_name]
                chosen_recipe_id = selected_recipe['id']
                
                # Доступный остаток в граммах
                current_stock_g = fridge_stocks.get(chosen_recipe_id, 0.0)
                st.caption(f"Доступно в холодильнике сейчас: {current_stock_g:.0f} г")
                
                # Вытаскиваем параметры шаблона рецепта
                base_portions = selected_recipe.get('default_servings') or selected_recipe.get('portions') or selected_recipe.get('portions_count') or 1
                base_portions = int(float(base_portions))
                est_cooked_w = int(float(selected_recipe.get('estimated_cooked_weight', 100)))
                
                # Расчет веса одной стандартной порции
                single_portion_w = max(50, int(est_cooked_w / base_portions))
                st.caption(f"ℹ️ Стандартная порция в рецепте ≈ {single_portion_w}г")
                
                # Переводим граммы из холодильника в эквивалент порций
                current_stock_portions = current_stock_g / single_portion_w
                
                # Ввод множителя порции для СЕБЯ (вместо сырых граммов)
                user_servings = st.number_input(
                    "Сколько порций планируете съесть лично вы?",
                    min_value=0.1, max_value=5.0, value=1.0, step=0.1,
                    key=f"user_servings_{meal_key}_{chosen_recipe_id}",
                    help="1.0 = стандартная порция. 1.2 = чуть больше."
                )
                
                # ИНТЕГРАЦИЯ МИКРО-ОСТАТКОВ: Работает, если ты планируешь доесть блюдо сам из холодильника
                if current_stock_g > 0:
                    remaining_tail_portions = current_stock_portions - user_servings
                    # Переводим хвост обратно в граммы для человеческого понимания
                    remaining_tail_g = remaining_tail_portions * single_portion_w
                    
                    # Если в холодильнике после твоего плана остается меньше 100 грамм еды
                    if 0 < remaining_tail_g < 100:
                        st.info(f"💡 В холодильнике останется всего {remaining_tail_g:.0f}г (~{remaining_tail_portions:.1f} порт.). Рекомендуем забрать весь остаток, чтобы закрыть позицию.")
                        if st.checkbox("🎯 Забрать весь остаток из холодильника", key=f"tail_{meal_key}_{chosen_recipe_id}"):
                            # Принудительно выставляем порции равными всему остатку в холодильнике
                            user_servings = float(current_stock_portions)
                
                # Информационный расчет планового веса для КБЖУ (округляем для красоты)
                estimated_user_weight = int(single_portion_w * user_servings)
                st.info(f"📐 Ваш плановый вес: ~{estimated_user_weight} г (Порций: {user_servings:.2f})")
                
                # На скольких человек закупка
                family_scale = st.number_input(
                    "На скольких человек готовить / закупаем всего?", 
                    min_value=1, max_value=10, value=3, step=1,
                    key=f"scale_{meal_key}"
                )
                
                # Опция масштабирования порций на всю семью
                scale_all = False
                if family_scale > 1:
                    scale_all = st.checkbox(
                        "Увеличить порции для всех", 
                        value=False,
                        key=f"scale_all_{meal_key}_{chosen_recipe_id}",
                        help="Если выбрано, то все члены семьи съедят по столько же, сколько и вы. Если нет — остальные съедят по 1.0 стандартной порции."
                    )

                if st.button("Добавить в план", key=f"save_plan_{meal_key}_{chosen_recipe_id}"):
                    actual_family_scale = st.session_state.get(f"scale_{meal_key}") or family_scale
                    actual_user_servings = st.session_state.get(f"user_servings_{meal_key}_{chosen_recipe_id}") or user_servings
                    actual_scale_all = st.session_state.get(f"scale_all_{meal_key}_{chosen_recipe_id}", False) if family_scale > 1 else False

                    # Считаем вес порции юзера (например, 100г * 1.2 = 120г)
                    final_user_weight = int(single_portion_w * float(actual_user_servings))

                    # Если галка стоит, делаем масштаб отрицательным (например, -4)
                    baked_family_scale = int(actual_family_scale)
                    if actual_scale_all:
                        baked_family_scale = -baked_family_scale 

                    # СТРОГИЙ PAYLOAD: Только то, что бэк 100% умеет принимать
                    payload = {
                        "user_id": str(USER_ID),
                        "date_day": str(date_str),
                        "meal_type": str(meal_key),
                        "recipe_id": int(chosen_recipe_id),
                        "weight_g": float(final_user_weight), 
                        "servings_multiplier": int(baked_family_scale) 
                    }
                    
                    print("ОТПРАВЛЯЕМ ЧИСТЫЙ PAYLOAD БЕЗ ЛИШНИХ ПОЛЕЙ:", payload)
                    
                    res = requests.post(f"{BASE_URL}/diary/", json=payload)
                    
                    # Выводим ошибку в интерфейс, если бэк всё равно откажет
                    if res.status_code == 200:
                        st.success("Успешно добавлено в план!")
                        st.rerun()
                    else:
                        st.error(f"Ошибка бэкенда: {res.status_code} - {res.text}")
# ==========================================
# ЭКРАН 2: МОЙ ХОЛОДИЛЬНИК (С КОРРЕКТИРОВКОЙ)
# ==========================================
elif menu == "🍲 Мой Холодильник":
    st.header("🍲 Мой Холодильник (Приготовленная еда)")
    st.write("Здесь хранится то, что вы уже сварили. Если домашние подьели часть еды без трекера, скорректируйте остаток вручную.")
    
    logs = get_all("recipes/cooking-logs")
    active_logs = [l for l in logs if not l['is_finished']]
    
    if not active_logs:
        st.info("Холодильник пуст. Самое время заглянуть в Книгу рецептов и что-нибудь приготовить!")
    else:
        recipes_list = get_all("recipes")
        recipe_names = {r['id']: r['name'] for r in recipes_list}
        
        for l in active_logs:
            name = recipe_names.get(l['recipe_id'], "Рецепт")
            
            with st.container(border=True):
                col_info, col_edit, col_action = st.columns([3, 2, 1])
                
                with col_info:
                    st.subheader(f"🥣 {name}")
                    st.write(f"**Остаток в кастрюле:** :green[{float(l['current_remaining_weight'])}г] из {float(l['total_cooked_weight'])}г")
                    st.caption(f"КБЖУ на 100г: Ккал: {l['calories_per_100g']} | Б: {l['proteins_per_100g']} | Ж: {l['fats_per_100g']} | У: {l['carbs_per_100g']}")
                
                with col_edit:
                    st.write("**Корректировка «на глаз»:**")
                    # Инпут для быстрого изменения веса остатка
                    new_remain = st.number_input(
                        "Фактический вес сейчас (г)",
                        min_value=0,
                        max_value=int(float(l['total_cooked_weight'])),
                        value=int(float(l['current_remaining_weight'])),
                        step=50,
                        key=f"edit_remain_{l['id']}"
                    )
                    
                    if st.button("💾 Обновить остаток", key=f"btn_update_{l['id']}", use_container_width=True):
                        res = requests.patch(
                            f"{BASE_URL}/recipes/cooking-logs/{l['id']}", 
                            json={"current_remaining_weight": new_remain}
                        )
                        if res.status_code == 200:
                            st.success("Остаток синхронизирован!")
                            st.rerun()
                        else:
                            st.error("Не удалось обновить вес")
                
                with col_action:
                    st.write("") # визуальный отступ
                    st.write("") 
                    if st.button("🗑️ Выбросить", key=f"del_pot_{l['id']}", type="secondary", use_container_width=True, help="Полностью удалить кастрюлю"):
                        res = requests.delete(f"{BASE_URL}/recipes/cooking-logs/{l['id']}")
                        if res.status_code == 204:
                            st.success("Удалено!")
                            st.rerun()

# ==========================================
# ЭКРАН 3: КНИГА РЕЦЕПТОВ (ПОЛНЫЙ ИСПРАВЛЕННЫЙ КОД)
# ==========================================
elif menu == "📖 Книга рецептов":
    st.header("📖 Ваша кулинарная книга (Шаблоны)")
    
    # Базовые запросы к бэкенду через твою функцию get_all
    recipes = get_all("recipes")
    products_data = get_all("products")
    
    # Получаем реальные категории рецептов из БД для проверки существования
    recipe_categories_list = get_all("recipes/categories") or get_all("recipe-categories")
    existing_categories = {c['name'].lower(): c['id'] for c in recipe_categories_list} if recipe_categories_list else {}
    
    # Собираем карты вариантов продуктов и их КБЖУ из структуры каталога
    variant_options = {}    # {"Название (Бренд / Производитель)": variant_id}
    variant_by_id = {}      # {variant_id: "Название..."}
    variant_nutrients = {}  # {variant_id: {"calories": X, "proteins": Y, ...}}
    
    for p in products_data:
        b_name = p.get('brand', {}).get('name', 'Без бренда')
        for m in p.get('manufacturers', []):
            for v in m.get('variants', []):
                if v.get('is_active', True):
                    display_name = f"{p['name']} ({b_name} / {m['name'] or 'Дефолт'})"
                    v_id = v['id']
                    
                    variant_options[display_name] = v_id
                    variant_by_id[v_id] = display_name
                    variant_nutrients[v_id] = {
                        "calories": float(v.get("calories", 0) or 0),
                        "proteins": float(v.get("proteins", 0) or 0),
                        "fats": float(v.get("fats", 0) or 0),
                        "carbs": float(v.get("carbs", 0) or 0)
                    }

    # Разделение экрана на системные вкладки Streamlit
    tab_list, tab_create = st.tabs(["📋 Доступные рецепты", "➕ Создать новый шаблон"])

# --- ВКЛАДКА 1: ПРОСМОТР И ПРИГОТОВЛЕНИЕ СУЩЕСТВУЮЩИХ ---
    with tab_list:
        if not recipes:
            st.info("В вашей кулинарной книге пока нет рецептов. Перейдите во вкладку 'Создать новый шаблон', чтобы добавить первый!")
        
        for r in recipes:
            with st.container(border=True):
                # Проверяем маркер нехранимого блюда в описании
                is_immediate = "[🔥 Нехранимое]" in r.get('description', '')
                badge = " 🍳 (Съедается сразу)" if is_immediate else " 🧊 (Хранимое)"
                
                st.subheader(f"🥣 {r['name']}{badge}")
		# УНИВЕРСАЛЬНЫЙ ХАК: ищем количество порций во всех возможных полях, которые мог вернуть бэк
                portions_base = r.get('default_servings') or r.get('portions') or r.get('portions_count') or 1
                portions_base = int(float(portions_base))
                
                st.caption(f"Базовый шаблон: {portions_base} порц. | Шаблон на 100г: {r['calories_per_100g']} ккал")
                
                # Показываем чистую инструкцию без системного тега
                clean_desc = r.get('description', '').replace("[🔥 Нехранимое]\n", "")
                if clean_desc:
                    st.markdown(f"*Инструкция:* {clean_desc}")

                # Ограничиваем логику интерфейса для нехранимых блюд на этапе MVP
                if is_immediate:
                    st.info("💡 Это блюдо моментального приготовления. Планируйте и фиксируйте его съедение напрямую через **Дневник питания**, чтобы гибко менять массу под конкретную дату.")
                else:
                    # Для хранимых блюд (супы, пловы) оставляем отправку кастрюли в холодильник
                    with st.popover("🍳 Я приготовил эту кастрюлю/большое блюдо"):
                        st.write("🔧 Скорректируйте состав кастрюли под то, что реально пошло в готовку:")
                        
                        custom_ingredients = []
                        
                        # ИСПРАВЛЕНИЕ: Добавляем enumerate(..., start=1), чтобы получить уникальный индекс строки ing_idx
                        for ing_idx, ing in enumerate(r['template_ingredients'], start=1):
                            v_id = ing['variant_id']
                            default_w = int(float(ing['weight_g']))
                            orig_name = variant_by_id.get(v_id, f"Вариант #{v_id}")
                            
                            st.markdown(f"**Ингредиент №{ing_idx}: {orig_name}**")
                            col_select, col_weight = st.columns([3, 1])
                            
                            with col_select:
                                all_variants_list = list(variant_options.keys())
                                default_index = all_variants_list.index(orig_name) if orig_name in all_variants_list else 0
                                
                                # ИСПРАВЛЕНИЕ КЛЮЧА: теперь в имя ключа подмешивается ing_idx, что гарантирует 100% уникальность
                                chosen_variant_name = st.selectbox(
                                    "Продукт для замены", all_variants_list, index=default_index,
                                    key=f"sel_rec_{r['id']}_ing_{ing_idx}_v_{v_id}", label_visibility="collapsed"
                                )
                                final_variant_id = variant_options[chosen_variant_name]
                                
                            with col_weight:
                                # ИСПРАВЛЕНИЕ КЛЮЧА: добавляем ing_idx и для поля ввода веса
                                actual_w = st.number_input(
                                    "Вес (г)", min_value=0, max_value=5000, value=default_w, step=10,
                                    key=f"w_rec_{r['id']}_ing_{ing_idx}_v_{v_id}", label_visibility="collapsed"
                                )
                                
                            if actual_w > 0:
                                custom_ingredients.append({
                                    "variant_id": final_variant_id, 
                                    "weight_g": str(actual_w)
                                })
                        
                        st.markdown("---")
                        cooked_weight = st.number_input(
                            "Фактический вес готового блюда (выход кастрюли, г)", 
                            min_value=50, max_value=5000, value=int(float(r['estimated_cooked_weight'])),
                            key=f"cook_weight_{r['id']}"
                        )
                        
                        if st.button("🧊 Поставить кастрюлю в холодильник", key=f"go_cook_{r['id']}"):
                            payload = {
                                "user_id": USER_ID,
                                "total_cooked_weight": cooked_weight,
                                "ingredients": custom_ingredients
                            }
                            res = requests.post(f"{BASE_URL}/recipes/{r['id']}/cook", json=payload)
                            if res.status_code == 200:
                                st.success("Успешно! Большая кастрюля отправлена в ваш виртуальныйходилник.")
                                st.rerun()

    # --- ВКЛАДКА 2: КОНСТРУКТОР НОВЫХ ШАБЛОНОВ ---
    with tab_create:
        st.subheader("🍳 Конструктор нового рецепта")
        
        if not variant_options:
            st.warning("В каталоге продуктов нет доступных вариантов. Сначала добавьте продукты на экране каталога.")
        else:
            # Инициализируем структуру динамических строк в session_state, если её нет
            if "new_recipe_ingredients" not in st.session_state:
                st.session_state.new_recipe_ingredients = [{"variant_name": list(variant_options.keys())[0], "weight": 100}]

            # 1. Основные метаданные рецепта
            col_r1, col_r2 = st.columns([2, 1])
            with col_r1:
                new_recipe_name = st.text_input("Название нового рецепта:", placeholder="Например: Яичница с томатами", key="create_rec_name")
            with col_r2:
                cat_input = st.text_input("Категория рецепта:", placeholder="Например: Завтраки", help="Если категории нет в базе, она создастся автоматически")
                
                # Валидация категории на лету
                if cat_input.strip():
                    if cat_input.strip().lower() in existing_categories:
                        st.caption("🟢 Будет использована существующая категория")
                    else:
                        st.caption("🟡 Будет создана новая категория")
                elif recipe_categories_list:
                    avail_cats = ", ".join([c['name'] for c in recipe_categories_list])
                    st.caption(f"В базе уже есть: {avail_cats}")
                else:
                    st.caption("🔴 База категорий пуста. Введите любое название.")

            new_recipe_desc = st.text_area("Инструкция / Описание рецепта:", placeholder="Шаг 1. Разбить яйца...", key="create_rec_desc")

            # 2. Параметры приготовления и чекбокс нехранимого блюда
            col_p1, col_p2, col_p3 = st.columns(3)
            with col_p1:
                cooking_time = st.number_input("Время готовки (мин):", min_value=1, max_value=480, value=15, step=5, key="create_rec_time")
            with col_p2:
                portions = st.number_input("Количество порций в шаблоне:", min_value=1, max_value=50, value=1, step=1, key="create_rec_portions")
            with col_p3:
                is_immediate_consume = st.checkbox("Съедается сразу", value=False, help="Отметьте для нехранимых блюд (яичница, кофе), которые не убирают в холодильник.")

            st.markdown("---")
            st.write("**🛒 Ингредиенты шаблона:**")

            # --- ХИТРЫЙ ХАК ДЛЯ СТРИМЛИТА: Считаем вес ДО отрисовки полей ---
            total_raw_weight = 0
            for idx, ing_item in enumerate(st.session_state.new_recipe_ingredients):
                # Проверяем, менял ли пользователь вес в number_input на прошлом шаге
                weight_key = f"new_rec_w_{idx}"
                if weight_key in st.session_state:
                    # Берем самое свежее значение прямо из состояния виджета
                    total_raw_weight += int(st.session_state[weight_key])
                else:
                    total_raw_weight += int(ing_item["weight"])

            total_cals, total_prots, total_fats, total_carbs = 0.0, 0.0, 0.0, 0.0
            ingredients_payload = []

            # Теперь спокойно отрисовываем поля ингредиентов
            for idx, ing_item in enumerate(st.session_state.new_recipe_ingredients):
                col_v_select, col_v_weight = st.columns([3, 1])
                
                with col_v_select:
                    chosen_name = st.selectbox(
                        f"Ингредиент №{idx+1}", options=list(variant_options.keys()),
                        index=list(variant_options.keys()).index(ing_item["variant_name"]),
                        key=f"new_rec_sel_{idx}"
                    )
                    st.session_state.new_recipe_ingredients[idx]["variant_name"] = chosen_name
                    selected_variant_id = variant_options[chosen_name]
                    nutrients = variant_nutrients[selected_variant_id]
                    
                with col_v_weight:
                    # Важно: onChange заставит форму пересчитаться без залипаний
                    v_weight = st.number_input(
                        f"Вес сырого (г) #{idx+1}", min_value=1, max_value=10000, 
                        value=int(ing_item["weight"]), step=10, key=f"new_rec_w_{idx}"
                    )
                    st.session_state.new_recipe_ingredients[idx]["weight"] = v_weight

                # Расчет КБЖУ для информационной плашки под строкой
                row_cals = (nutrients["calories"] * v_weight) / 100
                row_prots = (nutrients["proteins"] * v_weight) / 100
                row_fats = (nutrients["fats"] * v_weight) / 100
                row_carbs = (nutrients["carbs"] * v_weight) / 100

                total_cals += row_cals
                total_prots += row_prots
                total_fats += row_fats
                total_carbs += row_carbs

                ingredients_payload.append({"variant_id": selected_variant_id, "weight_g": v_weight})
                st.caption(f"🧬 Доля в рецепте: {row_cals:.1f} ккал | Б: {row_prots:.1f}г | Ж: {row_fats:.1f}г | У: {row_carbs:.1f}г")
                st.markdown("---")

            # Кнопки управления строками ПОД список ингредиентов
            col_add, col_rem = st.columns(2)
            with col_add:
                if st.button("➕ Добавить строку ингредиента", key="add_new_ing_line"):
                    st.session_state.new_recipe_ingredients.append({"variant_name": list(variant_options.keys())[0], "weight": 100})
                    st.rerun()
            with col_rem:
                if st.button("❌ Удалить последнюю строку", key="rem_new_ing_line") and len(st.session_state.new_recipe_ingredients) > 1:
                    st.session_state.new_recipe_ingredients.pop()
                    st.rerun()

            st.markdown("---")
            
            # --- ФИНАЛЬНЫЙ АВТОРАСЧЕТ ВЕСА ---
            # Меняем ключ динамически (добавляя total_raw_weight в имя ключа), 
            # чтобы Streamlit принудительно обновлял дефолтное значение поля при изменении суммы!
            est_cooked_weight = st.number_input(
                "Ожидаемый вес готового блюда (г):", 
                min_value=50, max_value=10000, 
                value=int(total_raw_weight),
                step=50, 
                key=f"rec_est_weight_sum_{total_raw_weight}", # Трюк с динамическим ключом
                help="По умолчанию равен сумме сырых ингредиентов. Скорректируйте вручную, если вес изменится при готовке."
            )

            # Суммарная плашка сырья
            st.write("**📊 Итоговый КБЖУ профиль сырых компонентов:**")
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Всего Калорий", f"{total_cals:.1f} ккал")
            mc2.metric("Всего Белков", f"{total_prots:.1f} г")
            mc3.metric("Всего Жиров", f"{total_fats:.1f} г")
            mc4.metric("Всего Углеводов", f"{total_carbs:.1f} г")

            # КБЖУ на 100г готового блюда (Пункт 7)
            if est_cooked_weight > 0:
                cals_100 = (total_cals / est_cooked_weight) * 100
                prots_100 = (total_prots / est_cooked_weight) * 100
                fats_100 = (total_fats / est_cooked_weight) * 100
                carbs_100 = (total_carbs / est_cooked_weight) * 100
                
                st.write(f"🧬 **Расчетный КБЖУ на 100г готового блюда:** {cals_100:.1f} ккал | Б: {prots_100:.1f}г | Ж: {fats_100:.1f}г | У: {carbs_100:.1f}г")

            # Кнопка сохранения шаблона рецепта в базу
            if st.button("💾 Сохранить новый шаблон", type="primary", key="commit_new_recipe_btn"):
                if not new_recipe_name.strip() or not cat_input.strip():
                    st.error("Пожалуйста, заполните название рецепта и категорию!")
                else:
                    cat_name_final = cat_input.strip()
                    cat_lower_final = cat_name_final.lower()
                    
                    if cat_lower_final in existing_categories:
                        selected_cat_id = existing_categories[cat_lower_final]
                    else:
                        with st.spinner("Создание новой категории рецепта..."):
                            c_res = requests.post(f"{BASE_URL}/recipes/categories/", json={"name": cat_name_final})
                            if c_res.status_code not in [200, 201]:
                                c_res = requests.post(f"{BASE_URL}/recipe-categories/", json={"name": cat_name_final})
                            selected_cat_id = c_res.json()['id'] if c_res.status_code in [200, 201] else 1
                    
                    final_instructions = new_recipe_desc.strip() if new_recipe_desc else ""
                    if is_immediate_consume:
                        final_instructions = f"[🔥 Нехранимое]\n{final_instructions}"

                    # ИСПРАВЛЕННЫЙ PAYLOAD: Ключи теперь строго по бэкенд-схеме RecipeCreate!
                    payload = {
                        "name": new_recipe_name.strip(),
                        "recipe_category_id": selected_cat_id,
                        "cooking_time_minutes": cooking_time,       # Было: cooking_time_min
                        "instructions": final_instructions,          # Было: description
                        "created_by_user": USER_ID,
                        "default_servings": portions,               # Было: portions
                        "estimated_cooked_weight": float(est_cooked_weight),
                        "ingredients": ingredients_payload
                    }
                    
                    res = requests.post(f"{BASE_URL}/recipes/", json=payload)
                    if res.status_code in [200, 201]:
                        st.success(f"🎉 Шаблон рецепта '{new_recipe_name}' успешно сохранен в базе!")
                        st.session_state.new_recipe_ingredients = [{"variant_name": list(variant_options.keys())[0], "weight": 100}]
                        # Чистим старые ключи весов из сессии, чтобы они не влияли на новый пустой рецепт
                        for k in list(st.session_state.keys()):
                            if k.startswith("new_rec_w_") or k.startswith("rec_est_weight_sum_"):
                                del st.session_state[k]
                        st.rerun()
                    else:
                        st.error(f"Ошибка сохранения рецепта: {res.status_code} -> {res.text}")
# ==========================================
# ЭКРАН 4: УМНЫЙ СПИСОК ПОКУПОК (ПО ДИАПАЗОНУ ДАТ)
# ==========================================
elif menu == "🛒 Список покупок":
    st.header("🛒 Генератор списка покупок")
    st.write("Система анализирует ваши планы на выбранный период и собирает суммарный вес ингредиентов ТОЛЬКО для тех блюд, которых еще нет в холодильнике.")
    
    # ТРЕБОВАНИЕ 2 (из верхнего списка): Выбор произвольного диапазона дат
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        start_date = st.date_input("С какой даты", date.today())
    with col_d2:
        end_date = st.date_input("По какую дату", date.today() + timedelta(days=7))
        
    if start_date > end_date:
        st.error("Дата окончания не может быть раньше даты начала!")
    else:
        if st.button("📋 Сгенерировать список покупок", type="primary"):
            # Делаем запрос к нашему умному эндпоинту
            res = requests.get(
                f"{BASE_URL}/diary/{USER_ID}/shopping-list",
                params={"start_date": start_date.strftime("%Y-%m-%d"), "end_date": end_date.strftime("%Y-%m-%d")}
            )
            
            if res.status_code == 200:
                shopping_list = res.json()
                if not shopping_list:
                    st.info("Для выбранного периода нет невыполненных планов питания. Докупать ничего не нужно!")
                else:
                    st.subheader(f"🛍️ Продукты для закупки с {start_date} по {end_date}:")
                    
                    # Выводим красивый чеклист
                    for item in shopping_list:
                        # Вес переводим в понятные кг, если его много
                        weight = item['weight_g']
                        weight_str = f"{weight:.0f} г" if weight < 1000 else f"{(weight/1000):.2f} кг"
                        
                        st.checkbox(f"**{item['product_name']}** — требуется {weight_str}", key=f"shop_{item['variant_id']}")
            else:
                st.error("Не удалось сгенерировать список покупок. Проверьте бэкенд.")

# ==========================================
# ЭКРАН 5: КАТАЛОГ ПРОДУКТОВ
# ==========================================
elif menu == "📦 Каталог продуктов":
    st.header("📦 Доступные базовые продукты")
    products_data = get_all("products")
    if products_data:
        flattened_products = []
        for p in products_data:
            brand_name = p.get('brand', {}).get('name', 'Без бренда')
            for m in p.get('manufacturers', []):
                for v in m.get('variants', []):
                    if v.get('is_active', True):
                        flattened_products.append({
                            "ID": p['id'], "Название": p['name'], "Бренд": brand_name, 
                            "Производитель": m['name'] or "Дефолт", "Калории": float(v['calories']), 
                            "Белки": float(v['proteins']), "Жиры": float(v['fats']), "Углеводы": float(v['carbs'])
                        })
        st.dataframe(pd.DataFrame(flattened_products), use_container_width=True, hide_index=True)

