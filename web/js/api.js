// HTTP-клиент Food Tracker API: JWT в localStorage, разбор ошибок FastAPI.
// Интерфейс раздаётся тем же процессом, что и API (/app), поэтому базовый URL — относительный.

const API = "/api/v1";
const TOKEN_KEY = "ft.token";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

function safeGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function safeSet(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* приватный режим — живём без сохранения */ }
}

let token = safeGet(TOKEN_KEY);
let onUnauthorized = () => {};

export const auth = {
  get token() { return token; },
  set(t) { token = t; safeSet(TOKEN_KEY, t); },
  clear() { token = null; safeSet(TOKEN_KEY, null); },
  onUnauthorized(fn) { onUnauthorized = fn; },
};

function extractDetail(body, status) {
  if (!body) return `HTTP ${status}`;
  const detail = body.detail ?? body;
  if (Array.isArray(detail)) {
    // 422 от pydantic: [{loc, msg}]
    return detail
      .map((e) => {
        const loc = (e.loc || []).filter((x) => x !== "body").join(".");
        const msg = String(e.msg || "").replace(/^Value error, /, "");
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("; ");
  }
  if (typeof detail === "object") return detail.message || JSON.stringify(detail);
  return String(detail);
}

async function request(method, path, { params, json, form } = {}) {
  let url = API + path;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) if (v != null) qs.set(k, v);
    url += (url.includes("?") ? "&" : "?") + qs;
  }
  const headers = {};
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = new URLSearchParams(form);
  }
  if (token) headers.Authorization = `Bearer ${token}`;

  let resp;
  try {
    resp = await fetch(url, { method, headers, body });
  } catch {
    throw new ApiError(0, "Сервер недоступен. Запущен ли uvicorn?");
  }
  if (resp.status === 204) return null;
  let data = null;
  const text = await resp.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text.slice(0, 300) }; }
  }
  if (resp.status === 401 && token) {
    auth.clear();
    onUnauthorized();
  }
  if (!resp.ok) throw new ApiError(resp.status, extractDetail(data, resp.status));
  return data;
}

export const api = {
  get: (p, params) => request("GET", p, { params }),
  post: (p, json, params) => request("POST", p, { json, params }),
  patch: (p, json) => request("PATCH", p, { json }),
  put: (p, json) => request("PUT", p, { json }),
  del: (p, params) => request("DELETE", p, { params }),

  async login(identifier, password) {
    const r = await request("POST", "/auth/login", { form: { identifier, password } });
    auth.set(r.access_token);
  },
  async register(username, email, password, invite_code) {
    await request("POST", "/auth/register", { json: { username, email, password, invite_code: invite_code || null } });
    await api.login(username, password);
  },
  me: () => request("GET", "/auth/me"),
};
