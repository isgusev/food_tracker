// Общее для экрана «planner»: константы и помощники компонентов.
import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Macros, MacroMeters, Modal } from "../../components.js";
import {
  state, ensureCatalog, toast, toastError, activeMembers, members, viewMember, setViewMember,
  targetsForMeters, hasTargets,
} from "../../store.js";
import {
  MEALS, MEAL_ORDER, addDays, fmt, fmtDayMonth, fmtDayMonthLong, fmtWeekday, fmtWeekdayLong,
  grams, local, n, range, startOfWeek, today,
} from "../../util.js";

import {
  AddItemModal, ItemModal, allEaten, itemBadge, itemIcon, memberMacros, portionOf, portionsSummary,
} from "../plan-modals.js";

export const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];

export const fmtMonth = (d) => MONTHS[Number(d.slice(5, 7)) - 1];

export function byMeal(items) {
  const out = Object.fromEntries(MEALS.map((m) => [m.key, []]));
  for (const it of items) (out[it.meal_type] ||= []).push(it);
  return out;
}
