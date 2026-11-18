// Общее для экрана «plan-modals»: константы и помощники компонентов.
import { ref, computed, watch } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, Macros } from "../../components.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError, activeVariantOf } from "../../product-finder.js";
import {
  state, toast, variantIndex, recipeById, recipeCategoryName, activeMembers, memberById,
} from "../../store.js";
import { MEALS, MEAL_LABEL, bjuLine, fmt, fmtQty, grams, local, n, packageGrams, fmtWeekday, fmtDayMonth } from "../../util.js";

// ---------- помощники для отображения блюда ----------

export const allEaten = (it) => it.portions.length > 0 && it.portions.every((p) => p.is_eaten);

export const portionOf = (it, memberId) => it.portions.find((p) => p.member_id === memberId) || null;

export function itemIcon(it) {
  if (allEaten(it)) return "✓";
  if (it.kind === "product") return "🛍";
  return it.state === "in_fridge" ? "◐" : "○";
}

export function itemBadge(it) {
  if (it.kind === "product") return { text: "Готовый продукт", cls: "info" };
  if (allEaten(it)) return { text: "Съедено", cls: "ok" };
  if (it.state === "in_fridge") {
    return it.fridge_enough === false
      ? { text: "В холодильнике не хватает", cls: "warn" }
      : { text: "Из холодильника", cls: "ok" };
  }
  if (it.fridge_pot_id && it.fridge_enough) {
    return { text: `Есть в холодильнике · свободно ${grams(n(it.fridge_available_g) - n(it.fridge_reserved_g))}`, cls: "info" };
  }
  if (it.fridge_pot_id) return { text: "Надо приготовить · в кастрюле не хватит", cls: "warn" };
  return { text: "Надо приготовить", cls: "warn" };
}

export function portionsSummary(it) {
  const named = it.portions.filter((p) => p.member_id != null).map((p) => `${p.member_name} ${fmt(p.weight_g)}`);
  const guests = it.portions.filter((p) => p.member_id == null);
  if (guests.length) named.push(guests.length === 1 ? `гость ${fmt(guests[0].weight_g)}` : `гости ×${guests.length}`);
  return named.join(" · ");
}

// Сумма КБЖУ порций одного члена семьи (onlyEaten — только съеденное)
export function memberMacros(items, memberId, onlyEaten = false) {
  const t = { calories: 0, proteins: 0, fats: 0, carbs: 0 };
  for (const it of items) {
    const p = portionOf(it, memberId);
    if (!p || (onlyEaten && !p.is_eaten)) continue;
    for (const k in t) t[k] += n(p[k]);
  }
  return t;
}

export const portionMemoryKey = (kind, id) => `ft.portions.${kind}.${id}`;
