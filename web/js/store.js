// Общее состояние: справочники (продукты, рецепты, категории), пользователь, уведомления.
import { reactive, computed } from "../vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { local, n } from "./util.js";

export const state = reactive({
  user: null,
  products: [],
  productCategories: [],
  recipes: [],
  recipeCategories: [],
  toasts: [],
  loaded: { products: false, recipes: false },
});

let toastSeq = 0;
export function toast(text, kind = "info", ms = 3500) {
  const id = ++toastSeq;
  state.toasts.push({ id, text, kind });
  setTimeout(() => {
    const i = state.toasts.findIndex((t) => t.id === id);
    if (i >= 0) state.toasts.splice(i, 1);
  }, ms);
}
export function toastError(e) {
  toast(e?.message || String(e), "error", 6000);
}

export async function loadProducts() {
  const [products, cats] = await Promise.all([
    api.get("/products/", { limit: 2000 }),
    api.get("/products/categories"),
  ]);
  state.products = products;
  state.productCategories = cats;
  state.loaded.products = true;
}

export async function loadRecipes() {
  const [recipes, cats] = await Promise.all([
    api.get("/recipes/", { limit: 500 }),
    api.get("/recipes/categories"),
  ]);
  state.recipes = recipes;
  state.recipeCategories = cats;
  state.loaded.recipes = true;
}

export async function ensureCatalog() {
  const jobs = [];
  if (!state.loaded.products) jobs.push(loadProducts());
  if (!state.loaded.recipes) jobs.push(loadRecipes());
  await Promise.all(jobs);
}

// ---------- Индексы ----------
export const categoryName = computed(() =>
  Object.fromEntries(state.productCategories.map((c) => [c.id, c.name]))
);
export const recipeCategoryName = computed(() =>
  Object.fromEntries(state.recipeCategories.map((c) => [c.id, c.name]))
);
export const recipeById = computed(() => Object.fromEntries(state.recipes.map((r) => [r.id, r])));

// variant_id → описание (продукт, бренд, производитель, КБЖУ, активна ли версия)
export const variantIndex = computed(() => {
  const idx = {};
  for (const p of state.products) {
    for (const m of p.manufacturers || []) {
      for (const v of m.variants || []) {
        const brand = p.brand?.name || "";
        const maker = m.name && m.name !== brand ? m.name : "";
        idx[v.id] = {
          id: v.id,
          product: p,
          manufacturer: m,
          variant: v,
          name: p.name,
          sub: [brand, maker].filter(Boolean).join(" · "),
          label: [p.name, brand].filter(Boolean).join(" · "),
          category: categoryName.value[p.category_id] || "",
          active: v.is_active,
          version: v.version,
          calories: n(v.calories),
          proteins: n(v.proteins),
          fats: n(v.fats),
          carbs: n(v.carbs),
        };
      }
    }
  }
  return idx;
});

// Варианты для выбора в формах: только активные версии КБЖУ
export const activeVariants = computed(() =>
  Object.values(variantIndex.value)
    .filter((v) => v.active)
    .sort((a, b) => a.category.localeCompare(b.category, "ru") || a.name.localeCompare(b.name, "ru"))
);

export function variantLabel(id) {
  const v = variantIndex.value[id];
  return v ? v.label : `Продукт #${id}`;
}

// ---------- Личные цели КБЖУ (пока хранятся в браузере, см. docs/REVIEW.md) ----------
const DEFAULT_TARGETS = { calories: 2000, proteins: 100, fats: 70, carbs: 230 };
export function getTargets() {
  return { ...DEFAULT_TARGETS, ...local.get(`ft.targets.${state.user?.id}`, {}) };
}
export function setTargets(t) {
  local.set(`ft.targets.${state.user?.id}`, t);
}
