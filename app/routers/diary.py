from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from decimal import Decimal

from app.database import get_db
from app import models, schemas

from datetime import date as date_type

router = APIRouter(
    prefix="/api/diary",
    tags=["Дневник питания пользователя"]
)

@router.get("/{user_id}/shopping-list")
def get_shopping_list(
    user_id: str, 
    start_date: date_type, 
    end_date: date_type, 
    db: Session = Depends(get_db)
):
    """
    Генерирует агрегированный список покупок за диапазон дат.
    Учитывает только блюда в статусе template_plan, масштабируя их на servings_multiplier.
    """
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    
    planned_meals = db.query(models.DiaryLog).filter(
        models.DiaryLog.user_id == user_id,
        models.DiaryLog.date_day >= start_str,
        models.DiaryLog.date_day <= end_str,
        models.DiaryLog.status.in_(["template_plan", "plan"])
    ).all()
    
    shopping_cart = {}
    
    for meal in planned_meals:
        recipe = meal.recipe
        if not recipe:
            continue
            
        base_servings = float(getattr(recipe, "default_servings", None) or getattr(recipe, "portions", None) or 1.0)
        estimated_recipe_weight = float(recipe.estimated_cooked_weight) or 1.0
        single_portion_weight = estimated_recipe_weight / base_servings
        
        # Восстанавливаем user_ratio (120г / 100г = 1.2)
        user_ratio = float(meal.weight_g) / single_portion_weight
        
        # Читаем масштаб из базы
        raw_multiplier = int(getattr(meal, "servings_multiplier", 1) or 1)
        
        # Если число отрицательное — значит, галка была нажата
        scale_all = raw_multiplier < 0
        total_people = float(abs(raw_multiplier))
        
        if total_people > 1:
            if scale_all:
                total_family_portions_needed = user_ratio * total_people
            else:
                total_family_portions_needed = user_ratio + (total_people - 1.0)
        else:
            total_family_portions_needed = user_ratio
            
        scale_factor = total_family_portions_needed / base_servings
        
        # Твой идеальный лог в консоли бэка
        print("\n" + "="*50)
        print(f"📋 ДЕТЕКТИВ ЛОГ ДЛЯ РЕЦЕПТА: {recipe.name}")
        print(f"1. Сырое число из БД (raw_multiplier): {raw_multiplier}")
        print(f"2. Восстановленный user_ratio: {user_ratio:.2f}")
        print(f"3. Реальный масштаб семьи: {total_people}")
        print(f"4. Флаг УВЕЛИЧИТЬ ВСЕМ (определен по минусу): {scale_all}")
        print(f"5. Коэффициент закупки (scale_factor): {scale_factor:.2f}")
        print("="*50 + "\n")
        
        for ing in recipe.template_ingredients:
            # ... твой стандартный код расчета веса ингредиентов ing.weight_g * scale_factor ...
            v_id = ing.variant_id
            needed_weight = float(ing.weight_g) * scale_factor
            # ... далее твой стандартный код сборки корзины ...
            
            # (Ниже идет твой стандартный код ORM-связей для сборки имени продукта)
            variant = ing.variant
            manufacturer = variant.manufacturer if variant else None
            product = manufacturer.product if manufacturer else None
            
            p_name = product.name if product else f"Продукт #{v_id}"
            b_name = product.brand.name if product and product.brand else ""
            m_name = manufacturer.name if manufacturer and manufacturer.name else ""
            full_display_name = f"{p_name} ({b_name} / {m_name})".replace("( / )", "").strip()
            
            if v_id not in shopping_cart:
                shopping_cart[v_id] = {
                    "name": full_display_name,
                    "weight_g": 0.0
                }
            shopping_cart[v_id]["weight_g"] += needed_weight
            
    return [
        {"variant_id": k, "product_name": v["name"], "weight_g": round(v["weight_g"], 1)}
        for k, v in shopping_cart.items()
    ]

@router.post("/", response_model=schemas.DiaryLogResponse)
def add_to_diary_plan(log_in: schemas.DiaryLogCreate, db: Session = Depends(get_db)):
    new_log = models.DiaryLog(
        user_id=log_in.user_id.strip(),
        date_day=log_in.date_day.strip(),
        meal_type=log_in.meal_type.strip(),
        status="plan",  # Оставляем чистый дефолт
        recipe_id=log_in.recipe_id,
        weight_g=log_in.weight_g,
        servings_multiplier=log_in.servings_multiplier # Сохраняем наше (возможно отрицательное) число
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    return new_log


@router.get("/{user_id}/{date_day}", response_model=List[schemas.DiaryLogResponse])
def get_diary_per_day(user_id: str, date_day: str, db: Session = Depends(get_db)):
    logs = db.query(models.DiaryLog).filter(
        models.DiaryLog.user_id == user_id,
        models.DiaryLog.date_day == date_day
    ).all()

    response_list = []
    for log in logs:
        res = schemas.DiaryLogResponse.from_orm(log)
        res.recipe_name = log.recipe.name if log.recipe else "Удаленный рецепт"
        
        # Определяем, по какому КБЖУ считать (точный инстанс или шаблон)
        if log.status in ["cooked_plan", "fact"] and log.cooking_log:
            source = log.cooking_log
        else:
            source = log.recipe

        if source:
            factor = log.weight_g / Decimal('100.0')
            res.calories = round(Decimal(str(source.calories_per_100g)) * factor, 1)
            res.proteins = round(Decimal(str(source.proteins_per_100g)) * factor, 1)
            res.fats = round(Decimal(str(source.fats_per_100g)) * factor, 1)
            res.carbs = round(Decimal(str(source.carbs_per_100g)) * factor, 1)
        
        response_list.append(res)
        
    return response_list

@router.patch("/{log_id}", response_model=schemas.DiaryLogResponse)
def update_diary_log_weight(log_id: int, weight_update: schemas.DiaryLogUpdateWeight, db: Session = Depends(get_db)):
    """ Просто меняет вес порции в дневнике (плановый или фактический), не переключая статус """
    log = db.query(models.DiaryLog).filter(models.DiaryLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Запись в дневнике не найдена")

    # Если запись уже была в статусе "fact", то изменение веса должно скорректировать холодильник!
    if log.status == "fact" and log.cooking_log_id:
        pot = db.query(models.RecipeCookingLog).filter(models.RecipeCookingLog.id == log.cooking_log_id).first()
        if pot:
            # Возвращаем старый вес в кастрюлю и вычитаем новый
            pot.current_remaining_weight += log.weight_g
            pot.current_remaining_weight -= weight_update.weight_g
            
            # Корректируем флаг финиша кастрюли
            pot.is_finished = pot.current_remaining_weight <= 0
            if pot.current_remaining_weight < 0:
                pot.current_remaining_weight = 0

    # Обновляем вес
    log.weight_g = weight_update.weight_g
    
    db.commit()
    db.refresh(log)
    return log

@router.patch("/{log_id}/eat", response_model=schemas.DiaryLogResponse)
def commit_or_change_fact(log_id: int, weight_update: schemas.DiaryLogUpdateWeight, db: Session = Depends(get_db)):
    """ Тот самый четверг: превращаем план в факт или меняем вес порции съеденного """
    log = db.query(models.DiaryLog).filter(models.DiaryLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Запись в дневнике не найдена")

    # Пытаемся привязать к холодильнику, если запись всё ещё висела в template_plan
    if not log.cooking_log_id:
        active_pot = db.query(models.RecipeCookingLog).filter(
            models.RecipeCookingLog.recipe_id == log.recipe_id,
            models.RecipeCookingLog.user_id == log.user_id,
            models.RecipeCookingLog.is_finished == False
        ).order_by(models.RecipeCookingLog.cooked_at.desc()).first()
        
        if active_pot:
            log.cooking_log_id = active_pot.id

    # Если мы переводим запись в статус "fact" (или меняем вес уже внутри существующего факта),
    # нам нужно скорректировать остаток в холодильнике
    if log.cooking_log_id:
        pot = db.query(models.RecipeCookingLog).filter(models.RecipeCookingLog.id == log.cooking_log_id).first()
        if pot:
            # Возвращаем старый вес порции обратно в кастрюлю (если это было редактирование факта)
            if log.status == "fact":
                pot.current_remaining_weight += log.weight_g
            
            # Вычитаем новый фактический вес
            pot.current_remaining_weight -= weight_update.weight_g
            
            if pot.current_remaining_weight <= 0:
                pot.current_remaining_weight = 0
                pot.is_finished = True
            else:
                pot.is_finished = False

    # Обновляем саму запись дневника
    log.weight_g = weight_update.weight_g
    log.status = "fact"
    
    db.commit()
    db.refresh(log)
    return log

@router.delete("/{log_id}", status_code=204)
def delete_diary_log(log_id: int, db: Session = Depends(get_db)):
    """Удаляет запись из дневника питания (план или факт)"""
    log = db.query(models.DiaryLog).filter(models.DiaryLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Запись в дневнике не найдена")
    
    db.delete(log)
    db.commit()
    return None

