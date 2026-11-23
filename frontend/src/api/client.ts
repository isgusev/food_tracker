// Типизированный клиент API: пути и тела — из OpenAPI (src/api/schema.d.ts, `npm run api`).
// JWT — в localStorage под тем же ключом, что у старого интерфейса (/app/): вход общий.
import createClient, { type Middleware } from "openapi-fetch";
import { reactive } from "vue";
import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
const TOKEN_KEY = "ft.token";

function read(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string | null): void {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* приватный режим — без сохранения */ }
}

let token = read(TOKEN_KEY);
let onUnauthorized: () => void = () => {};

export const auth = {
  get token() { return token; },
  set(t: string) { token = t; write(TOKEN_KEY, t); },
  clear() { token = null; write(TOKEN_KEY, null); },
  onUnauthorized(fn: () => void) { onUnauthorized = fn; },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** Текст ошибки FastAPI: detail строкой, объектом или списком ошибок pydantic (422). */
export function errorText(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail ?? body;
  if (Array.isArray(detail)) {
    return detail.map((e: { loc?: unknown[]; msg?: string }) => {
      const loc = (e.loc || []).filter((x) => x !== "body").join(".");
      const msg = String(e.msg || "").replace(/^Value error, /, "");
      return loc ? `${loc}: ${msg}` : msg;
    }).join("; ");
  }
  if (detail && typeof detail === "object") return (detail as { message?: string }).message || JSON.stringify(detail);
  return detail ? String(detail) : `HTTP ${status}`;
}

/** Есть ли связь с сервером. Ответ из сохранённой копии service worker помечает X-Offline-Copy (см. frontend/sw.js);
 *  сетевой сбой — тоже «нет». Любой живой ответ возвращает «да». */
export const network = reactive({ online: true });
if (typeof window !== "undefined") {
  window.addEventListener("offline", () => { network.online = false; });
  window.addEventListener("online", () => { network.online = true; });   // уточнит первый же запрос
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
  onResponse({ response }) {
    network.online = response.headers.get("X-Offline-Copy") !== "1";
    if (response.status === 401) { auth.clear(); onUnauthorized(); }
    return response;
  },
};

// fetch берём в момент запроса (а не при создании клиента) — так его можно подменить в проверках «нет сети»
export const api = createClient<paths>({ baseUrl: "", fetch: (req) => globalThis.fetch(req) });
api.use(authMiddleware);

/** Данные ответа или ApiError — чтобы в компонентах писать `const x = await ok(api.GET(...))`. */
export async function ok<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let res;
  try { res = await p; } catch { network.online = false; throw new ApiError(0, "Нет связи с сервером. Проверьте интернет и попробуйте ещё раз"); }
  if (res.error !== undefined || !res.response.ok) throw new ApiError(res.response.status, errorText(res.error, res.response.status));
  return res.data as T;
}
