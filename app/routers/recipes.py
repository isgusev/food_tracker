from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from decimal import Decimal

from app.database import get_db
from app import models, schemas

router = APIRouter(
    prefix="/api/recipes",
    tags=["Рецепты и Сложные Блюда"]
)

# --- КАТЕГОРИИ РЕЦЕПТОВ (С ЗАЩИТОЙ ОТ ДУБЛИРОВАНИЯ КИРИЛЛИЦЫ) ---

@router.post("/categories", response_model=schemas.RecipeCategoryResponse)
def create_recipe_category(category_in: schemas.RecipeCategoryCreate, db: Session = Depends(get_db)):
    display_name = category_in.name.strip()
    search_name = display_name.lower() # "Супы" -> "супы"

    # Защита от дублей на уровне Python (для обхода ограничений SQLite)
    existing = db.query(models.RecipeCategory).filter(models.RecipeCategory.search_name == search_name).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Категория рецептов '{display_name}' уже существует.")

    new_category = models.RecipeCategory(name=display_name, search_name=search_name)
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category

@router.get("/categories", response_model=List[schemas.RecipeCategoryResponse])
def get_recipe_categories(db: Session = Depends(get_db)):
    return db.query(models.RecipeCategory).all()


# --- БАЗОВЫЕ РЕЦЕПТЫ (ШАБЛОНЫ) ---

@router.post("/", response_model=schemas.RecipeResponse)
def create_recipe_template(recipe_in: schemas.RecipeCreate, db: Session = Depends(get_db)):
    # Проверяем, существует ли категория рецепта
    category = db.query(models.RecipeCategory).filter(models.RecipeCategory.id == recipe_in.recipe_category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Указанная категория рецептов не найдена")

    if not recipe_in.ingredients:
        raise HTTPException(status_code=400, detail="В рецепте должен быть минимум один ингредиент")
    
    if recipe_in.estimated_cooked_weight <= 0:
        raise HTTPException(status_code=400, detail="Планируемый вес готового блюда должен быть больше 0 грамм")

    # Переменные для расчета базового КБЖУ шаблона
    total_raw_weight = Decimal('0.0')
    total_calories = Decimal('0.0')
    total_proteins = Decimal('0.0')
    total_fats = Decimal('0.0')
    total_carbs = Decimal('0.0')

    db_ingredients = []

    # Считаем нутриенты сырого набора
    for ing in recipe_in.ingredients:
        if ing.weight_g <= 0:
            raise HTTPException(status_code=400, detail="Вес ингредиента должен быть больше 0 грамм")

        variant = db.query(models.ProductVariant).filter(models.ProductVariant.id == ing.variant_id).first()
        if not variant:
            raise HTTPException(status_code=404, detail=f"Версия продукта с ID {ing.variant_id} не найдена")

        weight_factor = ing.weight_g / Decimal('100.0')

        total_raw_weight += ing.weight_g
        total_calories += Decimal(str(variant.calories)) * weight_factor
        total_proteins += Decimal(str(variant.proteins)) * weight_factor
        total_fats += Decimal(str(variant.fats)) * weight_factor
        total_carbs += Decimal(str(variant.carbs)) * weight_factor

        db_ingredients.append(
            models.RecipeTemplateIngredient(variant_id=ing.variant_id, weight_g=ing.weight_g)
        )

    # Рассчитываем ориентировочное КБЖУ на 100г шаблона с учетом уварки по умолчанию
    cooked_factor = Decimal('100.0') / recipe_in.estimated_cooked_weight
    
    base_calories = total_calories * cooked_factor
    base_proteins = total_proteins * cooked_factor
    base_fats = total_fats * cooked_factor
    base_carbs = total_carbs * cooked_factor

    # Создаем шаблон рецепта
    new_recipe = models.Recipe(
        recipe_category_id=recipe_in.recipe_category_id,
        name=recipe_in.name.strip(),
        cooking_time_minutes=recipe_in.cooking_time_minutes,
        instructions=recipe_in.instructions.strip() if recipe_in.instructions else None,
        created_by_user=recipe_in.created_by_user.strip(),
        default_servings=recipe_in.default_servings,
        total_raw_weight=total_raw_weight,
        estimated_cooked_weight=recipe_in.estimated_cooked_weight,
        calories_per_100g=round(base_calories, 1),
        proteins_per_100g=round(base_proteins, 1),
        fats_per_100g=round(base_fats, 1),
        carbs_per_100g=round(base_carbs, 1),
        template_ingredients=db_ingredients
    )

    db.add(new_recipe)
    db.commit()
    db.refresh(new_recipe)
    return new_recipe

@router.get("/", response_model=List[schemas.RecipeResponse])
def get_recipes(db: Session = Depends(get_db)):
    return db.query(models.Recipe).all()


@router.post("/{recipe_id}/cook", response_model=schemas.RecipeCookingLogResponse)
def cook_recipe_instance(recipe_id: int, log_in: schemas.RecipeCookingLogCreate, db: Session = Depends(get_db)):
    recipe_template = db.query(models.Recipe).filter(models.Recipe.id == recipe_id).first()
    if not recipe_template:
        raise HTTPException(status_code=404, detail="Шаблон рецепта не найден")

    if not log_in.ingredients:
        raise HTTPException(status_code=400, detail="Нельзя приготовить блюдо без ингредиентов")

    if log_in.total_cooked_weight <= 0:
        raise HTTPException(status_code=400, detail="Вес готового блюда должен быть больше 0 грамм")

    total_raw_weight = Decimal('0.0')
    total_calories = Decimal('0.0')
    total_proteins = Decimal('0.0')
    total_fats = Decimal('0.0')
    total_carbs = Decimal('0.0')
    db_actual_ingredients = []

    for ing in log_in.ingredients:
        if ing.weight_g <= 0:
            raise HTTPException(status_code=400, detail="Вес ингредиента должен быть больше 0 грамм")
        variant = db.query(models.ProductVariant).filter(models.ProductVariant.id == ing.variant_id).first()
        if not variant:
            raise HTTPException(status_code=404, detail=f"Версия продукта {ing.variant_id} не найдена")

        weight_factor = ing.weight_g / Decimal('100.0')
        total_raw_weight += ing.weight_g
        total_calories += Decimal(str(variant.calories)) * weight_factor
        total_proteins += Decimal(str(variant.proteins)) * weight_factor
        total_fats += Decimal(str(variant.fats)) * weight_factor
        total_carbs += Decimal(str(variant.carbs)) * weight_factor

        db_actual_ingredients.append(
            models.RecipeActualIngredient(variant_id=ing.variant_id, weight_g=ing.weight_g)
        )

    cooked_factor = Decimal('100.0') / log_in.total_cooked_weight

    # Создаем инстанс в "холодильник"
    new_cooking_log = models.RecipeCookingLog(
        recipe_id=recipe_id,
        user_id=log_in.user_id.strip(),
        total_raw_weight=total_raw_weight,
        total_cooked_weight=log_in.total_cooked_weight,
        current_remaining_weight=log_in.total_cooked_weight, # Изначально кастрюля полная
        is_finished=False,
        calories_per_100g=round(total_calories * cooked_factor, 1),
        proteins_per_100g=round(total_proteins * cooked_factor, 1),
        fats_per_100g=round(total_fats * cooked_factor, 1),
        carbs_per_100g=round(total_carbs * cooked_factor, 1),
        actual_ingredients=db_actual_ingredients
    )
    db.add(new_cooking_log)
    db.commit()
    db.refresh(new_cooking_log)

    # АВТОМАТИЧЕСКОЕ УТОЧНЕНИЕ ПЛАНА:
    # Находим все будущие записи в планах этого пользователя, которые были "template_plan" по этому рецепту,
    # и привязываем их к свежей кастрюле, переводя в статус "cooked_plan"
    db.query(models.DiaryLog).filter(
        models.DiaryLog.user_id == log_in.user_id.strip(),
        models.DiaryLog.recipe_id == recipe_id,
        models.DiaryLog.status == "template_plan"
    ).update({
        "cooking_log_id": new_cooking_log.id,
        "status": "cooked_plan"
    }, synchronize_session=False)
    
    db.commit()
    return new_cooking_log

@router.get("/cooking-logs", response_model=List[schemas.RecipeCookingLogResponse])
def get_all_cooking_logs(db: Session = Depends(get_db)):
    return db.query(models.RecipeCookingLog).all()

@router.delete("/cooking-logs/{log_id}", status_code=204)
def delete_cooking_log(log_id: int, db: Session = Depends(get_db)):
    """Полностью удаляет кастрюлю из холодильника"""
    log = db.query(models.RecipeCookingLog).filter(models.RecipeCookingLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Запись готовки не найдена")
    
    # Опционально: если мы удаляем кастрюлю, связанные планы в дневнике (cooked_plan) 
    # должны откатиться обратно в статус примерного плана (template_plan)
    db.query(models.DiaryLog).filter(
        models.DiaryLog.cooking_log_id == log_id,
        models.DiaryLog.status == "cooked_plan"
    ).update({"status": "template_plan", "cooking_log_id": None})
    
    db.delete(log)
    db.commit()
    return None

@router.patch("/cooking-logs/{log_id}")
def update_cooking_log_weight(
    log_id: int, 
    payload: dict, # Принимаем {"current_remaining_weight": новое_значение}
    db: Session = Depends(get_db)
):
    """Позволяет вручную скорректировать остаток еды в кастрюле"""
    log = db.query(models.RecipeCookingLog).filter(models.RecipeCookingLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Запись готовки не найдена")
    
    new_weight = payload.get("current_remaining_weight")
    if new_weight is not None:
        log.current_remaining_weight = float(new_weight)
        
        # Если пользователь вручную скрутил кастрюлю в 0, помечаем её как съеденную
        if float(new_weight) <= 0:
            log.is_finished = True
            log.current_remaining_weight = 0.0
            
    db.commit()
    return {"status": "success", "current_remaining_weight": log.current_remaining_weight}