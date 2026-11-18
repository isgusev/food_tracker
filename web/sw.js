// Service worker: приложение открывается без сети, список покупок виден офлайн.
// Стратегия — «сначала сеть»: онлайн всегда свежая версия (после обновления
// сразу новые JS/CSS), офлайн — последняя сохранённая копия.
const CACHE = "ft-v7";
const SHELL = [
  "./", "index.html", "styles.css", "manifest.webmanifest", "icons/icon-192.png", "icons/icon.svg",
  "vendor/vue.esm-browser.prod.js", "vendor/zxing.min.js",
  // все модули web/js — scripts/check_web.sh проверяет, что список полный
  "js/api.js", "js/app.js", "js/components.js", "js/marking.js", "js/product-finder.js", "js/receipts.js",
  "js/store.js", "js/use-action.js", "js/util.js", "js/views/catalog.js", "js/views/catalog/CatalogView.js",
  "js/views/catalog/NewProductModal.js", "js/views/catalog/ProductModal.js", "js/views/fridge.js", "js/views/fridge/CookModal.js",
  "js/views/fridge/FridgeView.js", "js/views/fridge/PotModal.js", "js/views/items.js", "js/views/items/ItemsPanel.js",
  "js/views/items/MoveModal.js", "js/views/items/shared.js", "js/views/misc.js", "js/views/misc/FamilyView.js",
  "js/views/misc/LoginView.js", "js/views/misc/MemberCard.js", "js/views/misc/PlannerSettingsCard.js", "js/views/misc/shared.js",
  "js/views/money.js", "js/views/plan-modals.js", "js/views/plan-modals/AddItemModal.js", "js/views/plan-modals/ItemModal.js",
  "js/views/plan-modals/shared.js", "js/views/planner.js", "js/views/planner/DayView.js", "js/views/planner/MemberSwitch.js",
  "js/views/planner/PlannerView.js", "js/views/planner/TemplatesModal.js", "js/views/planner/shared.js",
  "js/views/recipes.js", "js/views/recipes/RecipeModal.js", "js/views/recipes/RecipesView.js", "js/views/shopping.js",
  "js/views/shopping/BoughtModal.js", "js/views/shopping/ExtraModal.js", "js/views/shopping/PackageModal.js",
  "js/views/shopping/RegularBlock.js", "js/views/shopping/ShoppingView.js", "js/views/shopping/shared.js",
  "js/views/stock.js", "js/views/stock/AddLotModal.js", "js/views/stock/ItemModal.js", "js/views/stock/QuickInventory.js",
  "js/views/stock/SplitLotModal.js", "js/views/stock/StockTab.js", "js/views/stock/shared.js",
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
