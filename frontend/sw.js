// Service worker нового интерфейса (/next/). Собирается Vite-плагином из vite.config.ts: он подставляет
// список файлов сборки (PRECACHE) и версию (VERSION) — новый деплой = новый sw.js = обновление.
//  · файлы сборки (assets/* с хешем в имени) — предзагружаются при установке и отдаются из кэша: экраны,
//    которые ещё не открывали, работают и без сети;
//  · страница (index.html) — «сначала сеть», без сети — сохранённая копия;
//  · чтение API — «сначала сеть», но если сеть молчит дольше 4 с, а копия есть — сразу копия (плохая связь
//    в магазине), ответ сети всё равно обновит её. Изменения (POST/PATCH/…) — только онлайн: отметки «куплено»
//    без сети копит само приложение (ft.shopQueue).
const VERSION = "__VERSION__";
const PRECACHE = __PRECACHE__;
const BASE = "/next/";
const SHELL = `ft-next-shell-${VERSION}`;
const API = "ft-next-api";            // общий для версий; при выходе приложение его стирает
const API_PREFIXES = [
  "/api/v1/auth/me", "/api/v1/household", "/api/v1/shopping-list", "/api/v1/finance", "/api/v1/products",
  "/api/v1/recipes", "/api/v1/plan", "/api/v1/stock", "/api/v1/items",
];
// поиск в Open Food Facts и по штрихкоду без сети бессмыслен, а кэш раздувает
const API_SKIP = ["/api/v1/products/off-search", "/api/v1/products/barcode/"];
const API_WAIT_MS = 4000;

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE.map((p) => BASE + p))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("ft-next-shell-") && k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

const put = (cache, req, res) => { if (res.ok && !res.redirected) caches.open(cache).then((c) => c.put(req, res)); };

// копию помечаем — приложение покажет «нет связи, показаны сохранённые данные»
function marked(res) {
  if (!res) return res;
  const headers = new Headers(res.headers);
  headers.set("X-Offline-Copy", "1");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

async function networkFirst(req, cache, waitMs) {
  const net = fetch(req).then((res) => { put(cache, req, res.clone()); return res; });
  const cached = caches.match(req, { cacheName: cache }).then(marked);
  if (waitMs) {
    // кто раньше: сеть или (через waitMs) копия, если она есть
    const late = new Promise((r) => setTimeout(r, waitMs)).then(() => cached).then((hit) => hit || net);
    return Promise.race([net, late]).catch(() => cached.then((hit) => hit || Response.error()));
  }
  return net.catch(() => cached.then((hit) => hit || Response.error()));
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  const p = url.pathname;

  if (p.startsWith(BASE + "assets/")) {           // имя с хешем — содержимое не меняется
    e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => { put(SHELL, req, res.clone()); return res; })));
  } else if (req.mode === "navigate" && p.startsWith(BASE)) {
    // любая страница под /next/ — это index.html (маршруты — после #): храним одну копию
    const page = BASE + "index.html";
    e.respondWith(fetch(req).then((res) => { put(SHELL, page, res.clone()); return res; })
      .catch(() => caches.match(page).then((hit) => hit || Response.error())));
  } else if (p.startsWith(BASE)) {
    e.respondWith(networkFirst(req, SHELL));
  } else if (API_PREFIXES.some((x) => p.startsWith(x)) && !API_SKIP.some((x) => p.startsWith(x))) {
    e.respondWith(networkFirst(req, API, API_WAIT_MS));
  }
});
