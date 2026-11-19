// Черновик продукта: найденный в Open Food Facts или введённый вручную. Пользователь проверяет цифры
// с упаковки, и продукт сохраняется в справочник (saveDraft).
import { api, ok, type Schemas } from "./api/client";
import { catalog, loadProducts } from "./catalog";
import { local, num } from "./util";

export const CODE_RE = /^\d{8,14}$/;
const LAST_CATEGORY = "ft.lastProductCategory";

type Num = number | string;
export interface Kbju { calories: Num; proteins: Num; fats: Num; carbs: Num }
export interface Draft {
  source: "openfoodfacts" | "manual";
  barcode: string | null;
  /** как пришло из поиска: поменяли название — это другой товар, штрихкод найденного сбрасывается */
  searchName: string | null;
  searchBarcode: string | null;
  name: string;
  brand: string;
  manufacturer: string;
  category: string;
  kbju: Kbju;
  package_amount: number | null;
  package_unit: string;
}
/** Подсказка Open Food Facts (или заготовка для ручного ввода). */
export type Suggestion = Partial<Schemas["BarcodeSuggestion"]>;

export const KBJU_KEYS = ["calories", "proteins", "fats", "carbs"] as const;
export const emptyKbju = (): Kbju => ({ calories: "", proteins: "", fats: "", carbs: "" });
const isBlank = (v: unknown) => v === "" || v == null;
export const kbjuEmpty = (k: Kbju) => KBJU_KEYS.every((key) => isBlank(k[key]));
export const kbjuIncomplete = (k: Kbju) => KBJU_KEYS.some((key) => isBlank(k[key]));

export function draftFrom(s: Suggestion, source: Draft["source"] = "openfoodfacts"): Draft {
  const off = source === "openfoodfacts";
  return {
    source,
    barcode: s.barcode || null,
    searchName: off ? s.name || "" : null,
    searchBarcode: off ? s.barcode || null : null,
    name: s.name || "",
    brand: s.brand || "",
    manufacturer: s.manufacturer || "",
    category: local.get<string>(LAST_CATEGORY, "") || "Готовые продукты",
    kbju: { calories: s.calories ?? "", proteins: s.proteins ?? "", fats: s.fats ?? "", carbs: s.carbs ?? "" },
    package_amount: s.package_amount ? num(s.package_amount) : null,
    package_unit: s.package_unit || "g",
  };
}

/** kbjuOptional — КБЖУ можно не вносить вовсе (покупки, чек): продукт сохранится «без КБЖУ». */
export function draftError(d: Draft, { kbjuOptional = false } = {}): string {
  if (!d.name.trim() || !d.category.trim()) return "Укажите название и категорию";
  if (kbjuOptional && kbjuEmpty(d.kbju)) return "";
  if (kbjuIncomplete(d.kbju)) return "Заполните КБЖУ на 100 г — с упаковки";
  return "";
}

/** Сохранить черновик в справочник; reuse — тот же штрихкод / название+бренд вернёт уже существующий. */
export async function saveDraft(d: Draft, { reuse = true } = {}): Promise<Schemas["ProductResponse"]> {
  const product = await ok(api.POST("/api/v1/products/with-category", {
    body: {
      category_name: d.category.trim(),
      name: d.name.trim(),
      brand_name: d.brand.trim() || "Без бренда",
      barcode: d.barcode && CODE_RE.test(d.barcode) ? d.barcode : null,
      package_amount: d.package_amount || null,
      package_unit: d.package_amount ? d.package_unit : null,
      reuse_existing: reuse,
      // КБЖУ не внесены — продукт сохраняется «на потом» (kbju_missing)
      base_variant: kbjuEmpty(d.kbju) ? null : {
        manufacturer_name: d.manufacturer.trim() || d.brand.trim() || null,
        calories: num(d.kbju.calories), proteins: num(d.kbju.proteins), fats: num(d.kbju.fats), carbs: num(d.kbju.carbs),
      },
    } as Schemas["ProductWithCategoryCreate"],
  }));
  local.set(LAST_CATEGORY, d.category.trim());
  await loadProducts();
  return product;
}

/** Активная версия КБЖУ продукта: у производителя с этикетки, иначе у первого. */
export function activeVariantOf(product: { id: number; manufacturers?: Schemas["ManufacturerResponse"][] | null }, maker?: string | null): number | null {
  const p = catalog.products.find((x) => x.id === product.id) || product;
  const want = (maker || "").trim().toLowerCase();
  const makers = [...(p.manufacturers || [])].sort((a, b) =>
    Number((b.name || "").toLowerCase() === want) - Number((a.name || "").toLowerCase() === want));
  for (const m of makers) {
    const v = (m.variants || []).find((x) => x.is_active);
    if (v) return v.id;
  }
  return null;
}
