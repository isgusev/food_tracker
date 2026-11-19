// Даты, числа, приёмы пищи — общее для экранов.
export const MEALS = [
  { key: "breakfast", label: "Завтрак", until: 11 },
  { key: "lunch", label: "Обед", until: 16 },
  { key: "dinner", label: "Ужин", until: 21 },
  { key: "snack", label: "Перекус", until: 24 },
] as const;
export type MealKey = (typeof MEALS)[number]["key"];
export const MEAL_LABEL: Record<string, string> = Object.fromEntries(MEALS.map((m) => [m.key, m.label]));

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
/** Какой приём пищи «сейчас» по часам. */
export function currentMeal(now = new Date()): MealKey {
  const h = now.getHours();
  return (MEALS.find((m) => h < m.until) ?? MEALS[3]).key;
}

const WEEKDAYS = ["воскресенье", "понедельник", "вторник", "среда", "четверг", "пятница", "суббота"];
const MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"];
export const weekday = (iso: string) => WEEKDAYS[new Date(iso + "T12:00:00").getDay()];
export const dayMonth = (iso: string) => `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]}`;

export const num = (v: unknown): number => {
  const x = typeof v === "number" ? v : parseFloat(String(v ?? "0"));
  return Number.isFinite(x) ? x : 0;
};
const nf0 = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 });
export const fmt = (v: unknown): string => nf0.format(num(v));
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
