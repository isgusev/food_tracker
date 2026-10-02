from pydantic import BaseModel
from typing import List, Optional
from decimal import Decimal

# --- КБЖУ (Версии) ---
class ProductVariantCreate(BaseModel):
    manufacturer_name: Optional[str] = None # Переносим сюда для Get-or-Create логики
    calories: Decimal
    proteins: Decimal
    fats: Decimal
    carbs: Decimal

class ProductVariantResponse(BaseModel):
    id: int
    manufacturer_id: int
    calories: Decimal
    proteins: Decimal
    fats: Decimal
    carbs: Decimal
    wrong_nutrients: bool
    version: int
    is_active: bool

    class Config:
        from_attributes = True

# --- ПРОИЗВОДИТЕЛИ ---
class ManufacturerResponse(BaseModel):
    id: int
    product_id: int
    name: Optional[str] = None
    variants: List[ProductVariantResponse] = []

    class Config:
        from_attributes = True

# --- БРЕНДЫ ---
class BrandResponse(BaseModel):
    id: int
    name: str 
    class Config:
        from_attributes = True

# --- ПРОДУКТЫ ---
class ProductCreate(BaseModel):
    category_id: int
    name: str
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    
    # Теперь создание продукта требует только базовый вариант (внутри которого есть имя завода)
    base_variant: ProductVariantCreate

class ProductResponse(BaseModel):
    id: int
    category_id: int
    name: str
    brand: BrandResponse
    is_verified: bool
    manufacturers: List[ManufacturerResponse] = []

    class Config:
        from_attributes = True

# --- КАТЕГОРИИ ---
class CategoryCreate(BaseModel):
    name: str

class CategoryResponse(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True

# --- ДОБАВИТЬ В КОНЕЦ ФАЙЛА app/schemas.py ---

# Категории рецептов
class RecipeCategoryCreate(BaseModel):
    name: str

class RecipeCategoryResponse(BaseModel):
    id: int
    name: str
    class Config:
        from_attributes = True

# Ингредиенты шаблона
class RecipeTemplateIngredientCreate(BaseModel):
    variant_id: int
    weight_g: Decimal

class RecipeTemplateIngredientResponse(BaseModel):
    id: int
    variant_id: int
    weight_g: Decimal
    class Config:
        from_attributes = True

# Шаблон Рецепта (База)
class RecipeCreate(BaseModel):
    name: str
    recipe_category_id: int
    cooking_time_minutes: Optional[int] = None
    instructions: Optional[str] = None
    created_by_user: Optional[str] = "system"
    default_servings: Optional[int] = 1
    estimated_cooked_weight: Decimal  # Планируемый вес готового блюда для каталога
    ingredients: List[RecipeTemplateIngredientCreate]

class RecipeResponse(BaseModel):
    id: int
    recipe_category_id: int
    name: str
    cooking_time_minutes: Optional[int]
    instructions: Optional[str]
    created_by_user: str
    default_servings: int
    total_raw_weight: Decimal
    estimated_cooked_weight: Decimal
    calories_per_100g: Decimal
    proteins_per_100g: Decimal
    fats_per_100g: Decimal
    carbs_per_100g: Decimal
    template_ingredients: List[RecipeTemplateIngredientResponse] = []

    class Config:
        from_attributes = True

# Реальные ингредиенты
class RecipeActualIngredientCreate(BaseModel):
    variant_id: int
    weight_g: Decimal

class RecipeActualIngredientResponse(BaseModel):
    id: int
    variant_id: int
    weight_g: Decimal
    class Config:
        from_attributes = True

# Лог Готовки (Инстанс Холодильника)
class RecipeCookingLogCreate(BaseModel):
    user_id: str
    total_cooked_weight: Decimal
    ingredients: List[RecipeActualIngredientCreate]

class RecipeCookingLogResponse(BaseModel):
    id: int
    recipe_id: Optional[int]
    user_id: str
    total_raw_weight: Decimal
    total_cooked_weight: Decimal
    current_remaining_weight: Decimal
    is_finished: bool
    calories_per_100g: Decimal
    proteins_per_100g: Decimal
    fats_per_100g: Decimal
    carbs_per_100g: Decimal
    actual_ingredients: List[RecipeActualIngredientResponse] = []
    class Config:
        from_attributes = True


class DiaryLogCreate(BaseModel):
    user_id: str
    date_day: str
    meal_type: str
    recipe_id: int
    weight_g: float
    servings_multiplier: Optional[int] = 1 # Оставляем только базовые поля!

class DiaryLogUpdateWeight(BaseModel):
    weight_g: Decimal

class DiaryLogResponse(BaseModel):
    id: int
    user_id: str
    date_day: str
    meal_type: str
    status: str
    recipe_id: Optional[int]
    cooking_log_id: Optional[int]
    weight_g: Decimal
    
    # Дополнительные поля, которые мы наполним в роутере для красоты UI
    recipe_name: Optional[str] = None
    calories: Decimal = Decimal('0.0')
    proteins: Decimal = Decimal('0.0')
    fats: Decimal = Decimal('0.0')
    carbs: Decimal = Decimal('0.0')

    class Config:
        from_attributes = True