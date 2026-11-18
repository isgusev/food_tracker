// Общее для экрана «misc»: константы и помощники компонентов.
import { ref, reactive, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { state, loadHousehold, loadRecipes, toast } from "../../store.js";
import { MEALS, fmt, local, n } from "../../util.js";

export const TARGET_KEYS = [
  { k: "calories", label: "Ккал" },
  { k: "proteins", label: "Белки, г" },
  { k: "fats", label: "Жиры, г" },
  { k: "carbs", label: "Углеводы, г" },
];

export const emptyToNull = (v) => (v === "" || v == null ? null : n(v));

// Расчёт целей: МР 2.3.1.0253-21 (Миффлин–Сан Жеор × КФА) + поправка на цель (app/services/nutrition.py)
export const ACTIVITY = [
  { v: 1.4, label: "Очень низкая: сидячая работа" },
  { v: 1.6, label: "Низкая: 1–3 тренировки в нед." },
  { v: 1.9, label: "Средняя: на ногах, 3–5 трен." },
  { v: 2.2, label: "Высокая: тяжёлый труд, спорт" },
];

export const GOALS = [
  { k: "lose", label: "Снижение" },
  { k: "maintain", label: "Поддержание" },
  { k: "gain", label: "Набор" },
];

export const PROFILE_KEYS = ["sex", "birth_year", "height_cm", "weight_kg", "activity", "goal"];
