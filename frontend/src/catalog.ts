// Справочник: продукты (с версиями КБЖУ и упаковками) и рецепты семьи — грузятся лениво, по одному разу.
import { computed, reactive } from "vue";
import { api, ok, type Schemas } from "./api/client";
import { num, packagesLabel } from "./util";

type Product = Schemas["ProductResponse"];
type Manufacturer = Schemas["ManufacturerResponse"];
type Variant = Schemas["ProductVariantResponse"];
type Recipe = Schemas["RecipeResponse"];

export const catalog = reactive({
  products: [] as Product[],
  productCategories: [] as Schemas["CategoryResponse"][],
  recipes: [] as Recipe[],
  recipeCategories: [] as Schemas["RecipeCategoryResponse"][],
  loaded: { products: false, recipes: false },
});

export async function loadProducts(): Promise<void> {
  const [products, cats] = await Promise.all([
    ok(api.GET("/api/v1/products/", { params: { query: { limit: 2000 } } })),
    ok(api.GET("/api/v1/products/categories")),
  ]);
  catalog.products = products;
  catalog.productCategories = cats;
  catalog.loaded.products = true;
}

export async function loadRecipes(): Promise<void> {
  const [recipes, cats] = await Promise.all([
    ok(api.GET("/api/v1/recipes/", { params: { query: { limit: 500 } } })),
    ok(api.GET("/api/v1/recipes/categories")),
  ]);
  catalog.recipes = recipes;
  catalog.recipeCategories = cats;
  catalog.loaded.recipes = true;
}

export async function ensureCatalog(): Promise<void> {
  await Promise.all([
    catalog.loaded.products ? null : loadProducts(),
    catalog.loaded.recipes ? null : loadRecipes(),
  ]);
}

export const categoryName = computed<Record<number, string>>(() =>
  Object.fromEntries(catalog.productCategories.map((c) => [c.id, c.name])));
export const recipeCategoryName = computed<Record<number, string>>(() =>
  Object.fromEntries(catalog.recipeCategories.map((c) => [c.id, c.name])));
export const recipeById = computed<Record<number, Recipe>>(() =>
  Object.fromEntries(catalog.recipes.map((r) => [r.id, r])));

/** Версия КБЖУ продукта с подписями для поиска и форм. */
export interface VariantInfo {
  id: number;
  product: Product;
  manufacturer: Manufacturer;
  variant: Variant;
  name: string;
  /** бренд · производитель (если отличается) */
  sub: string;
  /** + упаковки или «100 г» — для поиска */
  subFull: string;
  label: string;
  category: string;
  active: boolean;
  kbjuMissing: boolean;
  version: number;
  calories: number;
  proteins: number;
  fats: number;
  carbs: number;
}

export const variantIndex = computed<Record<number, VariantInfo>>(() => {
  const idx: Record<number, VariantInfo> = {};
  for (const p of catalog.products) {
    for (const m of p.manufacturers || []) {
      for (const v of m.variants || []) {
        const brand = p.brand?.name || "";
        const shownBrand = brand.toLowerCase() === "без бренда" ? "" : brand;
        const maker = m.name && m.name !== brand ? m.name : "";
        idx[v.id] = {
          id: v.id, product: p, manufacturer: m, variant: v, name: p.name,
          sub: [shownBrand, maker].filter(Boolean).join(" · "),
          subFull: [shownBrand, maker, packagesLabel(p.packages, p.base_unit)].filter(Boolean).join(" · "),
          label: [p.name, shownBrand].filter(Boolean).join(" · "),
          category: categoryName.value[p.category_id] || "",
          active: !!v.is_active, kbjuMissing: !!p.kbju_missing, version: v.version ?? 1,
          calories: num(v.calories), proteins: num(v.proteins), fats: num(v.fats), carbs: num(v.carbs),
        };
      }
    }
  }
  return idx;
});

/** Для выбора в формах — только активные версии, по категории и названию. */
export const activeVariants = computed<VariantInfo[]>(() =>
  Object.values(variantIndex.value).filter((v) => v.active)
    .sort((a, b) => a.category.localeCompare(b.category, "ru") || a.name.localeCompare(b.name, "ru")));

export const variantLabel = (id: number) => variantIndex.value[id]?.label ?? `Продукт #${id}`;
