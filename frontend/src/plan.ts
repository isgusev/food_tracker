// План: состояние блюда, порция едока, КБЖУ за период — общее для недели, дня и «Сегодня».
import type { Schemas } from "./api/client";
import { grams, num } from "./util";

export type Item = Schemas["MealItemResponse"];
export type Portion = Schemas["PortionResponse"];

export const allEaten = (it: Item) => it.portions.length > 0 && it.portions.every((p) => p.is_eaten);
export const portionOf = (it: Item, memberId: number | null) => it.portions.find((p) => p.member_id === memberId) ?? null;
/** Можно ли 🔄 «другой вариант»: рецепт, ещё не приготовлен и не съеден. */
export const canSwap = (it: Item) => it.kind === "recipe" && !it.cooking_log_id && !it.portions.some((p) => p.is_eaten);
/** Предложение можно «Убрать» при чистке черновика: без 📌, без кастрюли, без съеденного. */
export const isLooseDraft = (it: Item) => it.origin === "auto" && !it.pinned && !it.cooking_log_id && !it.portions.some((p) => p.is_eaten);
/** Полоса состояния: product | to_cook | in_fridge. */
export const stateClass = (it: Item) => "st-" + (it.kind === "product" ? "product" : it.state);

export function itemBadge(it: Item): { text: string; cls: "info" | "ok" | "warn" | "" } {
  if (it.kind === "product") return { text: "Готовый продукт", cls: "info" };
  if (allEaten(it)) return { text: "Съедено", cls: "ok" };
  if (it.state === "in_fridge") return it.fridge_enough === false
    ? { text: "В холодильнике не хватает", cls: "warn" } : { text: "Из холодильника", cls: "ok" };
  if (it.fridge_pot_id) {
    const free = num(it.fridge_available_g) - num(it.fridge_reserved_g);
    return it.fridge_enough
      ? { text: `Есть в холодильнике · свободно ${grams(free)}`, cls: "ok" }
      : { text: "Надо приготовить · в кастрюле не хватит", cls: "warn" };
  }
  return { text: "Надо приготовить", cls: "" };
}

export type Macros = { calories: number; proteins: number; fats: number; carbs: number };
/** Сумма КБЖУ порций едока (только съеденное — onlyEaten). */
export function memberMacros(items: Item[], memberId: number | null, onlyEaten = false): Macros {
  const t = { calories: 0, proteins: 0, fats: 0, carbs: 0 };
  for (const it of items) for (const p of it.portions) {
    if (p.member_id !== memberId || (onlyEaten && !p.is_eaten)) continue;
    t.calories += num(p.calories); t.proteins += num(p.proteins); t.fats += num(p.fats); t.carbs += num(p.carbs);
  }
  return t;
}
/** «Как в прошлый раз» — порции по рецепту (r) или версии продукта (v), тот же ключ, что у старого интерфейса. */
export const portionMemoryKey = (kind: "r" | "v", id: number) => `ft.portions.${kind}.${id}`;
