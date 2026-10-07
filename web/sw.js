// Service worker: приложение открывается без сети, список покупок виден офлайн.
// Стратегия — «сначала сеть»: онлайн всегда свежая версия (после обновления
// сразу новые JS/CSS), офлайн — последняя сохранённая копия.
const CACHE = "ft-v1";
const SHELL = [
  "./", "index.html", "styles.css", "manifest.webmanifest", "icons/icon-192.png",
  "vendor/vue.esm-browser.prod.js",
  "js/app.js", "js/api.js", "js/store.js", "js/util.js", "js/components.js",
  "js/views/planner.js", "js/views/plan-modals.js", "js/views/shopping.js", "js/views/fridge.js",
  "js/views/stock.js", "js/views/recipes.js", "js/views/catalog.js", "js/views/misc.js", "js/views/money.js",
];
// Ответы API, которые полезно иметь офлайн (только чтение)
const OFFLINE_API = ["/api/v1/shopping-lists/active", "/api/v1/auth/me", "/api/v1/household", "/api/v1/finance/prices"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;               // изменения — только онлайн (очередь — в приложении)
  const url = new URL(req.url);
  const isShell = url.pathname.startsWith("/app/");
  const isOfflineApi = OFFLINE_API.includes(url.pathname);
  if (!isShell && !isOfflineApi) return;
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: isShell }).then((hit) => hit || Response.error()))
  );
});
