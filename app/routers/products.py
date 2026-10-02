from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from decimal import Decimal

from app.database import get_db
from app import models, schemas

router = APIRouter(
    prefix="/api/products",
    tags=["Продукты, Производители и Версии КБЖУ"]
)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def check_nutrients_error(calories: Decimal, proteins: Decimal, fats: Decimal, carbs: Decimal) -> bool:
    calculated_calories = (Decimal('4') * proteins) + (Decimal('9') * fats) + (Decimal('4') * carbs)
    return abs(calories - calculated_calories) > Decimal('5')


def get_or_create_brand(brand_name: str, db: Session) -> int:
    display_name = brand_name.strip()
    search_name = display_name.lower()
    existing_brand = db.query(models.Brand).filter(models.Brand.search_name == search_name).first()
    if existing_brand:
        return existing_brand.id
    new_brand = models.Brand(name=display_name, search_name=search_name)
    db.add(new_brand)
    db.commit()
    db.refresh(new_brand)
    return new_brand.id


def get_or_create_manufacturer(product_id: int, m_name: Optional[str], db: Session) -> models.ProductManufacturer:
    display_name = m_name.strip() if m_name else None
    search_name = display_name.lower() if display_name else None

    existing_m = db.query(models.ProductManufacturer).filter(
        models.ProductManufacturer.product_id == product_id,
        models.ProductManufacturer.search_name == search_name
    ).first()

    if existing_m:
        return existing_m

    new_m = models.ProductManufacturer(product_id=product_id, name=display_name, search_name=search_name)
    db.add(new_m)
    db.commit()
    db.refresh(new_m)
    return new_m


# --- КАТЕГОРИИ ---
@router.post("/categories", response_model=schemas.CategoryResponse)
def create_category(category: schemas.CategoryCreate, db: Session = Depends(get_db)):
    normalized_name = category.name.strip().lower()
    db_category = db.query(models.ProductCategory).filter(models.ProductCategory.name.ilike(normalized_name)).first()
    if db_category:
        raise HTTPException(status_code=400, detail="Такая категория уже существует")
    new_category = models.ProductCategory(name=category.name.strip())
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category

@router.get("/categories", response_model=List[schemas.CategoryResponse])
def get_categories(db: Session = Depends(get_db)):
    return db.query(models.ProductCategory).all()


# --- ПРОДУКТЫ ---
@router.post("/", response_model=schemas.ProductResponse)
def create_product(product: schemas.ProductCreate, db: Session = Depends(get_db)):
    category = db.query(models.ProductCategory).filter(models.ProductCategory.id == product.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    if product.brand_id is not None:
        brand_exists = db.query(models.Brand).filter(models.Brand.id == product.brand_id).first()
        if not brand_exists:
            raise HTTPException(status_code=404, detail="Указанный ID бренда не найден")
        brand_id = product.brand_id
    elif product.brand_name:
        brand_id = get_or_create_brand(product.brand_name, db)
    else:
        raise HTTPException(status_code=400, detail="Укажите либо brand_id, либо brand_name")

    # 1. Принудительно переводим входящее имя в нижний регистр средствами Python
    prod_name = product.name.strip()
    prod_search_name = prod_name.lower() # "ТеЛяТИНА" -> "телятина"

    # 2. Ищем в базе точное совпадение по полю search_name (обычное равенство == работает в SQLite без сбоев)
    existing_product = db.query(models.Product).filter(
        models.Product.category_id == product.category_id,
        models.Product.brand_id == brand_id,
        models.Product.search_name == prod_search_name  # Сравниваем "телятина" == "телятина"
    ).first()

    if existing_product:
        raise HTTPException(
            status_code=400, 
            detail=f"Продукт с именем '{prod_name}' для этого бренда уже существует (регистр не имеет значения)."
        )

    # 3. Создаем продукт и ОБЯЗАТЕЛЬНО пишем в search_name нижний регистр
    new_product = models.Product(
        category_id=product.category_id, 
        brand_id=brand_id, 
        name=prod_name,
        search_name=prod_search_name  # Сохраняем "телятина"
    )
    db.add(new_product)
    db.commit()
    db.refresh(new_product)

    # Получаем/создаем производителя
    v = product.base_variant
    manufacturer = get_or_create_manufacturer(new_product.id, v.manufacturer_name, db)

    # Создаем Версию 1 КБЖУ
    is_wrong = check_nutrients_error(v.calories, v.proteins, v.fats, v.carbs)
    new_variant = models.ProductVariant(
        manufacturer_id=manufacturer.id,
        calories=v.calories,
        proteins=v.proteins,
        fats=v.fats,
        carbs=v.carbs,
        wrong_nutrients=is_wrong,
        version=1,
        is_active=True
    )
    db.add(new_variant)
    db.commit()
    db.refresh(new_product)

    return new_product

@router.get("/", response_model=List[schemas.ProductResponse])
def get_products(db: Session = Depends(get_db)):
    return db.query(models.Product).all()


# --- ДОБАВЛЕНИЕ/ОБНОВЛЕНИЕ КБЖУ ---
@router.post("/{product_id}/variants", response_model=schemas.ProductVariantResponse)
def add_variant_to_product(product_id: int, variant_in: schemas.ProductVariantCreate, db: Session = Depends(get_db)):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Продукт не найден")

# 1. Запускаем умный Get-or-Create для производителя
    manufacturer = get_or_create_manufacturer(product_id, variant_in.manufacturer_name, db)

    # 2. Ищем текущую активную версию КБЖУ, чтобы её потом погасить
    current_active = db.query(models.ProductVariant).filter(
        models.ProductVariant.manufacturer_id == manufacturer.id,
        models.ProductVariant.is_active == True
    ).first()

    # ЗАЩИТА: проверяем дубликат данных с текущей активной версией
    if current_active:
        if (current_active.calories == variant_in.calories and
            current_active.proteins == variant_in.proteins and
            current_active.fats == variant_in.fats and
            current_active.carbs == variant_in.carbs):
            raise HTTPException(status_code=400, detail="Данные идентичны текущей активной версии")

    # НАДЕЖНЫЙРАСЧЕТ СЛЕДУЮЩЕЙ ВЕРСИИ:
    # Ищем самый большой номер версии у этого производителя, независимо от её активности
    last_version_entry = db.query(models.ProductVariant).filter(
        models.ProductVariant.manufacturer_id == manufacturer.id
    ).order_by(models.ProductVariant.version.desc()).first()

    # Новая версия всегда строго больше, чем абсолютно последняя созданная
    next_version = (last_version_entry.version + 1) if last_version_entry else 1

    # Гасим старую активную версию (если она была)
    if current_active:
        current_active.is_active = False

    # 3. Создаем новую инкрементированную версию КБЖУ
    is_wrong = check_nutrients_error(variant_in.calories, variant_in.proteins, variant_in.fats, variant_in.carbs)

    new_variant = models.ProductVariant(
        manufacturer_id=manufacturer.id,
        calories=variant_in.calories,
        proteins=variant_in.proteins,
        fats=variant_in.fats,
        carbs=variant_in.carbs,
        wrong_nutrients=is_wrong,
        version=next_version,
        is_active=True
    )
    db.add(new_variant)
    db.commit()
    db.refresh(new_variant)
    return new_variant


# --- ТВОЯ ПРАВКА №2: УМНЫЙ ОТКАТ НА ПРЕДЫДУЩУЮ ВЕРСИЮ ---
@router.post("/{product_id}/manufacturers/{manufacturer_id}/rollback", response_model=schemas.ProductVariantResponse)
def rollback_to_previous_version(product_id: int, manufacturer_id: int, db: Session = Depends(get_db)):
    """
    Автоматический откат активных КБЖУ на предыдущую версию (текущая_версия - 1)
    для конкретного производителя внутри продукта.
    """
    # 1. Проверяем, существует ли такой производитель у данного продукта
    manufacturer = db.query(models.ProductManufacturer).filter(
        models.ProductManufacturer.id == manufacturer_id,
        models.ProductManufacturer.product_id == product_id
    ).first()
    
    if not manufacturer:
        raise HTTPException(status_code=404, detail="Указанный производитель для данного продукта не найден")

    # 2. Находим текущую активную версию
    current_active = db.query(models.ProductVariant).filter(
        models.ProductVariant.manufacturer_id == manufacturer_id,
        models.ProductVariant.is_active == True
    ).first()

    if not current_active:
        raise HTTPException(status_code=404, detail="У этого производителя нет активной версии КБЖУ")

    # 3. Проверяем, есть ли к чему откатываться
    if current_active.version <= 1:
        raise HTTPException(status_code=400, detail="Невозможно откатиться: у этого производителя только одна версия данных (Версия 1)")

    # 4. Ищем предыдущую по порядку версию (текущая версия минус 1)
    target_version_number = current_active.version - 1
    previous_variant = db.query(models.ProductVariant).filter(
        models.ProductVariant.manufacturer_id == manufacturer_id,
        models.ProductVariant.version == target_version_number
    ).first()

    if not previous_variant:
        raise HTTPException(status_code=404, detail=f"Предыдущая версия №{target_version_number} не найдена в истории")

    # 5. Проводим рокировку: гасим текущую, зажигаем предыдущую
    current_active.is_active = False
    previous_variant.is_active = True
    
    db.commit()
    db.refresh(previous_variant)
    
    return previous_variant