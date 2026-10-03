"""Каталог продуктов: просмотр с пагинацией и добавление."""
from __future__ import annotations

import streamlit as st

from ui import api_client


def _load_products() -> list[dict]:
    return api_client.get("products/", params={"limit": 500, "offset": 0}) or []


def render() -> None:
    st.header("📦 Каталог продуктов")

    with st.expander("➕ Добавить продукт"):
        with st.form("add_product_form", clear_on_submit=True):
            name = st.text_input("Название продукта *")
            col_a, col_b = st.columns(2)
            with col_a:
                category_name = st.text_input(
                    "Категория (создастся, если нет) *",
                    placeholder="Например: Крупы",
                )
                brand = st.text_input("Бренд / производитель", value="Без бренда")
            with col_b:
                kcal = st.number_input("Ккал на 100 г *", 0.0, 9999.0, 0.0, 0.1)
                p = st.number_input("Белки, г *", 0.0, 999.0, 0.0, 0.1)
                f = st.number_input("Жиры, г *", 0.0, 999.0, 0.0, 0.1)
                c = st.number_input("Углеводы, г *", 0.0, 999.0, 0.0, 0.1)
            if st.form_submit_button("Сохранить продукт"):
                if not name.strip() or not category_name.strip():
                    st.warning("Заполните название и категорию.")
                else:
                    try:
                        api_client.post(
                            "products/with-category",
                            {
                                "category_name": category_name.strip(),
                                "name": name.strip(),
                                "brand_name": brand.strip() or "Без бренда",
                                "base_variant": {
                                    "manufacturer_name": brand.strip() or None,
                                    "calories": kcal,
                                    "proteins": p,
                                    "fats": f,
                                    "carbs": c,
                                },
                            },
                        )
                        st.success(f"Продукт «{name}» добавлен.")
                        st.rerun()
                    except api_client.ApiError as exc:
                        st.error(str(exc))

    search = st.text_input("Поиск по названию", placeholder="греч...").strip().lower()

    try:
        products = _load_products()
    except api_client.ApiError as exc:
        st.error(str(exc))
        return

    if search:
        products = [p for p in products if search in p["name"].lower()]

    st.caption(f"Всего продуктов: {len(products)}")

    for product in products:
        title = product["name"]
        brand = (product.get("brand") or {}).get("name")
        if brand:
            title += f" · {brand}"
        with st.expander(title):
            for manufacturer in product.get("manufacturers", []):
                st.markdown(f"**{manufacturer['name'] or 'Без производителя'}**")
                variants = sorted(
                    manufacturer.get("variants", []),
                    key=lambda v: v["version"],
                    reverse=True,
                )
                for variant in variants[:3]:  # последние версии КБЖУ
                    flag = " ⚠️ (ошибка в данных)" if variant["wrong_nutrients"] else ""
                    st.write(
                        f"v{variant['version']}{flag}: "
                        f"{float(variant['calories']):.1f} ккал · "
                        f"Б {float(variant['proteins']):.1f} · "
                        f"Ж {float(variant['fats']):.1f} · "
                        f"У {float(variant['carbs']):.1f} (на 100 г)"
                    )
