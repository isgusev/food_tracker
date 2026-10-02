from sqlalchemy import Column, Integer, String, Boolean, Numeric, ForeignKey, DateTime, UniqueConstraint, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

# --- БЛОК КАТАЛОГА ПРОДУКТОВ (Остается без изменений) ---
class ProductCategory(Base):
    __tablename__ = "product_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    
    # Указывает на Product.category
    products = relationship("Product", back_populates="category")

class Brand(Base):
    __tablename__ = "brands"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    search_name = Column(String(255), unique=True, nullable=False)
    products = relationship("Product", back_populates="brand")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("product_categories.id", ondelete="RESTRICT"), nullable=False)
    brand_id = Column(Integer, ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(255), nullable=False)
    search_name = Column(String(255), nullable=False)
    is_verified = Column(Boolean, default=False)
    
    # Теперь указывает на ProductCategory.products
    category = relationship("ProductCategory", back_populates="products") # <-- ИСПРАВЛЕНО
    brand = relationship("Brand", back_populates="products")
    manufacturers = relationship("ProductManufacturer", back_populates="product", cascade="all, delete-orphan")

class ProductManufacturer(Base):
    __tablename__ = "product_manufacturers"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=True, default=None) 
    search_name = Column(String(255), nullable=True, default=None) 
    product = relationship("Product", back_populates="manufacturers")
    variants = relationship("ProductVariant", back_populates="manufacturer", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint('product_id', 'search_name', name='_product_manufacturer_uc'),)

class ProductVariant(Base):
    __tablename__ = "product_variants"
    id = Column(Integer, primary_key=True, index=True)
    manufacturer_id = Column(Integer, ForeignKey("product_manufacturers.id", ondelete="CASCADE"), nullable=False)
    calories = Column(Numeric(5, 1), nullable=False)
    proteins = Column(Numeric(4, 1), nullable=False)
    fats = Column(Numeric(4, 1), nullable=False)
    carbs = Column(Numeric(4, 1), nullable=False)
    wrong_nutrients = Column(Boolean, default=False, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    created_by_user = Column(String(100), nullable=False, default="system")
    is_rejected = Column(Boolean, default=False, nullable=False)
    is_approved = Column(Boolean, default=False, nullable=False)
    manufacturer = relationship("ProductManufacturer", back_populates="variants")
    __table_args__ = (UniqueConstraint('manufacturer_id', 'version', name='_manufacturer_version_uc'),)


# --- БЛОК ПОЛЬЗОВАТЕЛЕЙ ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False)
    search_username = Column(String(50), unique=True, nullable=False)
    email = Column(String(255), nullable=False)
    search_email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# --- БЛОК РЕЦЕПТОВ И ХОЛОДИЛЬНИКА ---
class RecipeCategory(Base):
    __tablename__ = "recipe_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    search_name = Column(String(100), unique=True, nullable=False)
    recipes = relationship("Recipe", back_populates="recipe_category")

class Recipe(Base):
    """ ШАБЛОН РЕЦЕПТА """
    __tablename__ = "recipes"
    id = Column(Integer, primary_key=True, index=True)
    recipe_category_id = Column(Integer, ForeignKey("recipe_categories.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(255), nullable=False)
    cooking_time_minutes = Column(Integer, nullable=True)
    instructions = Column(Text, nullable=True)
    created_by_user = Column(String(100), nullable=False, default="system")
    default_servings = Column(Integer, default=1, nullable=False)
    total_raw_weight = Column(Numeric(6, 1), default=0.0, nullable=False)
    estimated_cooked_weight = Column(Numeric(6, 1), nullable=False) 
    calories_per_100g = Column(Numeric(5, 1), default=0.0, nullable=False)
    proteins_per_100g = Column(Numeric(4, 1), default=0.0, nullable=False)
    fats_per_100g = Column(Numeric(4, 1), default=0.0, nullable=False)
    carbs_per_100g = Column(Numeric(4, 1), default=0.0, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    recipe_category = relationship("RecipeCategory", back_populates="recipes")
    template_ingredients = relationship("RecipeTemplateIngredient", back_populates="recipe", cascade="all, delete-orphan")
    cooking_logs = relationship("RecipeCookingLog", back_populates="recipe")

    # --- ЗАДЕЛ НА БУДУЩЕЕ ---
    is_public = Column(Boolean, default=False) # Флаг для расшаривания в общую базу
    ai_generated = Column(Boolean, default=False) # Маркер, что рецепт придуман нейросетью

class RecipeTemplateIngredient(Base):
    __tablename__ = "recipe_template_ingredients"
    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False)
    weight_g = Column(Numeric(5, 1), nullable=False)
    recipe = relationship("Recipe", back_populates="template_ingredients")
    variant = relationship("ProductVariant")

class RecipeCookingLog(Base):
    """ ИНСТАНС ГОТОВКИ (НАШ ХОЛОДИЛЬНИК) """
    __tablename__ = "recipe_cooking_logs"
    id = Column(Integer, primary_key=True, index=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(String(100), nullable=False)
    cooked_at = Column(DateTime, server_default=func.now())
    
    total_raw_weight = Column(Numeric(6, 1), nullable=False)
    total_cooked_weight = Column(Numeric(6, 1), nullable=False) 
    
    # УЛУЧШЕНИЕ: Храним остаток еды в кастрюле
    current_remaining_weight = Column(Numeric(6, 1), nullable=False)
    is_finished = Column(Boolean, default=False, nullable=False) # Кастрюля пуста?

    calories_per_100g = Column(Numeric(5, 1), nullable=False)
    proteins_per_100g = Column(Numeric(4, 1), nullable=False)
    fats_per_100g = Column(Numeric(4, 1), nullable=False)
    carbs_per_100g = Column(Numeric(4, 1), nullable=False)
    
    actual_ingredients = relationship("RecipeActualIngredient", back_populates="cooking_log", cascade="all, delete-orphan")
    recipe = relationship("Recipe", back_populates="cooking_logs")
    diary_entries = relationship("DiaryLog", back_populates="cooking_log")

    # --- ЗАДЕЛ НА БУДУЩЕЕ ---
    household_id = Column(String, index=True, nullable=True) # ID семьи для общего холодильника

class RecipeActualIngredient(Base):
    __tablename__ = "recipe_actual_ingredients"
    id = Column(Integer, primary_key=True, index=True)
    cooking_log_id = Column(Integer, ForeignKey("recipe_cooking_logs.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(Integer, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False)
    weight_g = Column(Numeric(5, 1), nullable=False)
    cooking_log = relationship("RecipeCookingLog", back_populates="actual_ingredients")
    variant = relationship("ProductVariant")


# ==========================================
# ФИНАЛЬНЫЙ БОСС: ДНЕВНИК ПИТАНИЯ (НОВЫЙ)
# ==========================================

class DiaryLog(Base):
    """
    ДНЕВНИК ПИТАНИЯ: Объединяет планы, уточненные планы и факты приемов пищи.
    """
    __tablename__ = "diary_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(100), nullable=False)
    
    # На какую дату запись (например, "2026-06-04")
    date_day = Column(String(10), nullable=False) 
    
    # Прием пищи: "breakfast", "lunch", "dinner", "snack"
    meal_type = Column(String(20), nullable=False)
    
    # ТРИ СТАТУСА: "template_plan", "cooked_plan", "fact"
    status = Column(String(20), default="template_plan", nullable=False)
    
    # Связи (Может ссылаться ИЛИ на шаблон рецепта, ИЛИ на конкретную готовку)
    recipe_id = Column(Integer, ForeignKey("recipes.id", ondelete="SET NULL"), nullable=True)
    cooking_log_id = Column(Integer, ForeignKey("recipe_cooking_logs.id", ondelete="SET NULL"), nullable=True)
    
    # Сколько грамм пользователь планирует съесть или уже съел по факту
    weight_g = Column(Numeric(5, 1), nullable=False)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    recipe = relationship("Recipe")

    #НОВАЯ_ЕСЛИ ЧТО УДАЛИМ
    scale_all_proportions = Column(Boolean, default=False, nullable=True)

    # --- ЗАДЕЛ НА БУДУЩЕЕ ---
    cooking_log = relationship("RecipeCookingLog", back_populates="diary_entries")
    household_id = Column(String, index=True, nullable=True) # Чтобы видеть планы друг друга
    servings_multiplier = Column(Integer, default=1) # Множитель порций (на сколько человек готовим/закупаем)