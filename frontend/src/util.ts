// Даты, числа, приёмы пищи — общее для экранов.
export const MEALS = [
  { key: "breakfast", label: "Завтрак", until: 11 },
  { key: "lunch", label: "Обед", until: 16 },
  { key: "dinner", label: "Ужин", until: 21 },
  { key: "snack", label: "Перекус", until: 24 },
] as const;
export type MealKey = (typeof MEALS)[number]["key"];
export const MEAL_LABEL: Record<string, string> = Object.fromEntries(MEALS.map((m) => [m.key, m.label]));
export const MEAL_ORDER: Record<string, number> = Object.fromEntries(MEALS.map((m, i) => [m.key, i]));

/** Местная дата YYYY-MM-DD (не UTC). */
export function isoDate(d = new Date()): string {
  const z = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
export const today = (): string => isoDate();
export function addDays(iso: string, k: number): string {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + k);
  return isoDate(d);
}
/** Понедельник недели, в которую входит дата. */
export function startOfWeek(iso: string): string {
  const d = new Date(iso + "T12:00:00");
  return addDays(iso, -((d.getDay() + 6) % 7));
}
export function range(start: string, end: string): string[] {
  const out: string[] = [];
  for (let d = start; d <= end; d = addDays(d, 1)) out.push(d);
  return out;
}
/** Какой приём пищи «сейчас» по часам. */
export function currentMeal(now = new Date()): MealKey {
  const h = now.getHours();
  return (MEALS.find((m) => h < m.until) ?? MEALS[3]).key;
}

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const WD_SHORT = ["вс", "пн", "вт", "ср", "чт", "пт", "сб"];
const MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
export const weekday = (iso: string) => WEEKDAYS[new Date(iso + "T12:00:00").getDay()];
export const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
export const dayMonth = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;
export const dayMonthShort = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS_SHORT[Number(iso.slice(5, 7)) - 1]}`;
export const weekdayShort = (iso: string) => WD_SHORT[new Date(iso + "T12:00:00").getDay()];
export const monthOf = (iso: string) => MONTHS[Number(iso.slice(5, 7)) - 1];
export const dayNum = (iso: string) => Number(iso.slice(8, 10));
/** «19 нояб., 14:05» — метка времени с сервера. */
export const dateTime = (s?: string | null) =>
  s ? new Date(s).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

export const num = (v: unknown): number => {
  const x = typeof v === "number" ? v : parseFloat(String(v ?? "0"));
  return Number.isFinite(x) ? x : 0;
};
export const fmt = (v: unknown, digits = 0): string =>
  num(v).toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
export const grams = (v: unknown): string => {
  const x = num(v);
  return x >= 1000 ? `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(x / 1000)} кг` : `${fmt(x)} г`;
};
/** 1 порция / 2 порции / 5 порций */
export function plural(n: number, one: string, few: string, many: string): string {
  const a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

// ---------- Количества и упаковки ----------
export const UNIT_LABEL: Record<string, string> = { g: "г", ml: "мл", pcs: "шт" };
export function fmtQty(v: unknown, unit = "g"): string {
  const x = num(v);
  if (unit === "pcs") return `${fmt(x, x % 1 ? 1 : 0)} шт`;
  if (unit === "ml") return x >= 1000 ? `${fmt(x / 1000, x % 1000 === 0 ? 0 : 2)} л` : `${fmt(x, x % 1 ? 1 : 0)} мл`;
  return grams(x);
}
/** Граммы (рецепт, порция) → единица товара; штучное без веса штуки остаётся в граммах. */
export const gramsToBase = (g: unknown, unit: string, pieceWeight: unknown) =>
  unit === "pcs" && num(pieceWeight) > 0 ? num(g) / num(pieceWeight) : num(g);
/** Упаковка → граммы для порций: мл = г, штуки — через вес одной. */
export const packageGrams = (amount: unknown, unit: string, pieceWeight: unknown) =>
  unit === "pcs" ? num(amount) * num(pieceWeight) : num(amount);
/** «930 мл», «200 г / 400 г …»; нет упаковки — «100 г» (КБЖУ на 100 г). */
export function packagesLabel(packages: { amount: unknown }[] | null | undefined, unit = "g"): string {
  const list = (packages || []).slice(0, 2).map((p) => fmtQty(p.amount, unit));
  return list.length ? list.join(" / ") + ((packages || []).length > 2 ? " …" : "") : "100 г";
}
/** Б/Ж/У в результатах поиска: до десятых, если меньше 10; нет — «—». */
export const fmtMacro = (v: unknown) => (v == null || v === "" ? "—" : fmt(v, num(v) % 1 && num(v) < 10 ? 1 : 0));
export const bjuLine = (m: { proteins?: unknown; fats?: unknown; carbs?: unknown }) =>
  `Б ${fmtMacro(m.proteins)} · Ж ${fmtMacro(m.fats)} · У ${fmtMacro(m.carbs)}`;

// ---------- Поиск ----------
/** Без регистра, «ё» → «е», без кавычек. */
export function norm(s: unknown): string {
  return String(s ?? "").toLowerCase().replace(/ё/g, "е").replace(/[«»"“”„'`]/g, " ").replace(/\s+/g, " ").trim();
}
function lev(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = row[0]; row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cur = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = cur;
    }
  }
  return row[b.length];
}
const similar = (a: string, b: string) => 1 - lev(a, b) / Math.max(a.length, b.length);
const words = (s: string) => norm(s).split(/[^\p{L}\p{N}%.,]+/u).filter(Boolean);
/** Похожесть запроса на текст (0…1) — то же правило, что match_score на сервере: целое слово 1, начало 0,9,
 *  вхождение ≥ 3 символов 0,85, опечатка (≥ 75 % похожести, слова ≥ 4) 0,8×; среднее по словам запроса. */
export function fuzzyScore(query: string, text: string): number {
  const qs = words(query), ts = words(text);
  if (!qs.length || !ts.length) return 0;
  let sum = 0;
  for (const q of qs) {
    let best = 0;
    for (const t of ts) {
      if (t === q) { best = 1; break; }
      if (q.length >= 2 && t.startsWith(q)) best = Math.max(best, 0.9);
      else if (t.includes(q) && q.length >= 3) best = Math.max(best, 0.85);
      else if (q.length >= 4 && t.length >= 4) {
        const r = Math.max(similar(q, t), similar(q, t.slice(0, q.length)));
        if (r >= 0.75) best = Math.max(best, 0.8 * r);
      }
    }
    sum += best;
  }
  return sum / qs.length;
}
/** Все слова запроса — подстроки текста. */
export function matches(haystack: string, query: string): boolean {
  const q = norm(query);
  if (!q) return true;
  const h = norm(haystack);
  return q.split(/\s+/).every((part) => h.includes(part));
}

// ---------- localStorage — только удобства ----------
export const local = {
  get<T>(key: string, fallback: T): T {
    try { const v = localStorage.getItem(key); return v == null ? fallback : (JSON.parse(v) as T); } catch { return fallback; }
  },
  set(key: string, value: unknown): void {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* приватный режим */ }
  },
};
