// Форматирование, даты, константы предметной области.

export const MEALS = [
  { key: "breakfast", label: "Завтрак" },
  { key: "lunch", label: "Обед" },
  { key: "dinner", label: "Ужин" },
  { key: "snack", label: "Перекус" },
];
export const MEAL_LABEL = Object.fromEntries(MEALS.map((m) => [m.key, m.label]));
export const MEAL_ORDER = Object.fromEntries(MEALS.map((m, i) => [m.key, i]));

export const STATUS = {
  template_plan: { label: "План", icon: "○", cls: "" },
  cooked_plan: { label: "План · в холодильнике", icon: "◐", cls: "info" },
  fact: { label: "Съедено", icon: "✓", cls: "ok" },
};

// ---------- Даты (локальные, без часовых сдвигов) ----------
export function iso(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
export function parseIso(s) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
}
export function addDays(s, n) {
  const d = parseIso(s);
  d.setDate(d.getDate() + n);
  return iso(d);
}
export function today() { return iso(new Date()); }
export function startOfWeek(s) {
  const d = parseIso(s);
  const dow = (d.getDay() + 6) % 7; // Пн = 0
  d.setDate(d.getDate() - dow);
  return iso(d);
}
export function daysBetween(a, b) {
  return Math.round((parseIso(b) - parseIso(a)) / 86400000);
}
export function range(start, end) {
  const out = [];
  for (let d = start; d <= end; d = addDays(d, 1)) out.push(d);
  return out;
}
const WD = new Intl.DateTimeFormat("ru-RU", { weekday: "short" });
const WD_LONG = new Intl.DateTimeFormat("ru-RU", { weekday: "long" });
const DM = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" });
const DML = new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
export const fmtWeekday = (s) => cap(WD.format(parseIso(s)));
export const fmtWeekdayLong = (s) => cap(WD_LONG.format(parseIso(s)));
export const fmtDayMonth = (s) => DM.format(parseIso(s)).replace(".", "");
export const fmtDayMonthLong = (s) => DML.format(parseIso(s));
export function fmtDateTime(s) {
  if (!s) return "";
  return new Date(s).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

// ---------- Числа ----------
export const n = (v) => (v == null || v === "" ? 0 : Number(v));
export function fmt(v, digits = 0) {
  return n(v).toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function grams(v) {
  const x = n(v);
  if (x >= 1000) return `${fmt(x / 1000, x % 1000 === 0 ? 0 : 2)} кг`;
  return `${fmt(x, x % 1 ? 1 : 0)} г`;
}

export function sumMacros(rows) {
  const t = { calories: 0, proteins: 0, fats: 0, carbs: 0 };
  for (const r of rows) {
    t.calories += n(r.calories);
    t.proteins += n(r.proteins);
    t.fats += n(r.fats);
    t.carbs += n(r.carbs);
  }
  return t;
}

// Поиск без учёта регистра и «ё»
export function norm(s) {
  return String(s || "").toLowerCase().replace(/ё/g, "е").trim();
}
export function matches(haystack, query) {
  const q = norm(query);
  if (!q) return true;
  const h = norm(haystack);
  return q.split(/\s+/).every((part) => h.includes(part));
}

// localStorage — только для удобств (выбранная неделя, отмеченные покупки, цели)
export const local = {
  get(key, fallback) {
    try {
      const v = localStorage.getItem(key);
      return v == null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
  },
};

// Количество в единице товара: г/кг, мл/л, шт
export const UNIT_LABEL = { g: "г", ml: "мл", pcs: "шт" };
export function fmtQty(v, unit = "g") {
  const x = n(v);
  if (unit === "pcs") return `${fmt(x, x % 1 ? 1 : 0)} шт`;
  if (unit === "ml") return x >= 1000 ? `${fmt(x / 1000, x % 1000 === 0 ? 0 : 2)} л` : `${fmt(x, x % 1 ? 1 : 0)} мл`;
  return grams(x);
}
// Граммы (рецепт, порция) → единица товара
export function gramsToBase(g, unit, pieceWeight) {
  return unit === "pcs" && n(pieceWeight) > 0 ? n(g) / n(pieceWeight) : n(g);
}

// Упаковка товара → граммы (для порций): мл = г, штуки — через вес одной
export function packageGrams(amount, unit, pieceWeight) {
  return unit === "pcs" ? n(amount) * n(pieceWeight) : n(amount);
}
// Подпись упаковок для поиска: «930 мл», «200 г / 400 г»; нет упаковки — «100 г» (КБЖУ на 100 г)
export function packagesLabel(packages, unit = "g") {
  const list = (packages || []).slice(0, 2).map((p) => fmtQty(p.amount, unit));
  return list.length ? list.join(" / ") + ((packages || []).length > 2 ? " …" : "") : "100 г";
}
