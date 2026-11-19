// Общее состояние нового интерфейса: кто вошёл, семья, чьи КБЖУ показываем, тосты.
import { computed, reactive } from "vue";
import { api, auth, ok, type Schemas } from "./api/client";

type Household = Schemas["HouseholdResponse"];
type Member = Schemas["MemberResponse"];
type Toast = { id: number; text: string; kind: "info" | "error" };

export const session = reactive({
  user: null as Schemas["UserResponse"] | null,
  household: null as Household | null,
  viewMemberId: null as number | null,
  ready: false,
  toasts: [] as Toast[],
});

let toastId = 0;
export function toast(text: string, kind: Toast["kind"] = "info", ms = 3500): void {
  const id = ++toastId;
  session.toasts.push({ id, text, kind });
  setTimeout(() => { session.toasts = session.toasts.filter((t) => t.id !== id); }, ms);
}
export const toastError = (e: unknown) => toast(e instanceof Error ? e.message : String(e), "error", 6000);

// тот же ключ, что у старого интерфейса: выбранный член семьи общий
const memberKey = () => `ft.viewMember.${session.user?.id}`;

export async function loadSession(): Promise<void> {
  if (!auth.token) { session.ready = true; return; }
  try {
    session.user = await ok(api.GET("/api/v1/auth/me"));
    session.household = await ok(api.GET("/api/v1/household"));
    let saved: number | null = null;
    try { saved = JSON.parse(localStorage.getItem(memberKey()) || "null"); } catch { /* нет хранилища */ }
    const ids = activeMembers.value.map((m) => m.id);
    session.viewMemberId = saved != null && ids.includes(saved) ? saved : session.household.me_member_id;
  } catch {
    auth.clear();
    session.user = null;
  } finally {
    session.ready = true;
  }
}

export function setViewMember(id: number): void {
  session.viewMemberId = id;
  try { localStorage.setItem(memberKey(), JSON.stringify(id)); } catch { /* нет хранилища */ }
}

export function logout(): void {
  auth.clear();
  session.user = null;
  session.household = null;
}

export const activeMembers = computed<Member[]>(() => (session.household?.members ?? []).filter((m) => m.is_active));
export const viewMember = computed<Member | null>(() => activeMembers.value.find((m) => m.id === session.viewMemberId) ?? null);

// ---- Личные цели КБЖУ (хранятся у члена семьи на сервере)
export type Macros4 = { calories: number; proteins: number; fats: number; carbs: number };
const DEFAULT_TARGETS: Macros4 = { calories: 2000, proteins: 100, fats: 70, carbs: 230 };
/** Цели; незаданные — null. */
export function targetsOf(m: Member | null | undefined): Record<keyof Macros4, number | null> {
  const t = (m?.targets ?? {}) as Record<string, unknown>;
  const out = {} as Record<keyof Macros4, number | null>;
  for (const k of Object.keys(DEFAULT_TARGETS) as (keyof Macros4)[]) out[k] = t[k] != null ? Number(t[k]) : null;
  return out;
}
/** Для полосок: незаданные цели — ориентир 2000 / 100 / 70 / 230. */
export function targetsForMeters(m: Member | null | undefined): Macros4 {
  const t = targetsOf(m);
  return { calories: t.calories ?? DEFAULT_TARGETS.calories, proteins: t.proteins ?? DEFAULT_TARGETS.proteins,
    fats: t.fats ?? DEFAULT_TARGETS.fats, carbs: t.carbs ?? DEFAULT_TARGETS.carbs };
}
export const hasTargets = (m: Member | null | undefined) => Object.values(targetsOf(m)).some((v) => v != null);
export const memberById = computed<Record<number, Member>>(() =>
  Object.fromEntries((session.household?.members ?? []).map((m) => [m.id, m])));
