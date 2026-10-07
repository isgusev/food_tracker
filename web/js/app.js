// Точка входа: hash-роутер, оболочка (меню), авторизация.
import { createApp, ref, computed, onMounted, onBeforeUnmount } from "../vendor/vue.esm-browser.prod.js";
import { api, auth } from "./api.js";
import { state, loadHousehold } from "./store.js";
import { local } from "./util.js";
import { PlannerView, DayView } from "./views/planner.js";
import { ShoppingView } from "./views/shopping.js";
import { FridgeView } from "./views/fridge.js";
import { RecipesView } from "./views/recipes.js";
import { CatalogView } from "./views/catalog.js";
import { LoginView, FamilyView } from "./views/misc.js";

const theme = local.get("ft.theme", "auto");
if (theme !== "auto") document.documentElement.setAttribute("data-theme", theme);

const NAV = [
  { path: "plan", label: "План", icon: "📅" },
  { path: "shopping", label: "Покупки", icon: "🛒" },
  { path: "fridge", label: "Холодильник", icon: "🧊" },
  { path: "recipes", label: "Рецепты", icon: "🍲" },
  { path: "catalog", label: "Продукты", icon: "📦" },
  { path: "family", label: "Семья", icon: "👪" },
];

function parseHash() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs] = raw.split("?");
  const parts = path.split("/").filter(Boolean);
  return { name: parts[0] || "plan", param: parts[1], query: Object.fromEntries(new URLSearchParams(qs || "")) };
}

const App = {
  components: { PlannerView, DayView, ShoppingView, FridgeView, RecipesView, CatalogView, LoginView, FamilyView },
  setup() {
    const route = ref(parseHash());
    const ready = ref(false);
    const onHash = () => { route.value = parseHash(); window.scrollTo(0, 0); };
    onMounted(() => window.addEventListener("hashchange", onHash));
    onBeforeUnmount(() => window.removeEventListener("hashchange", onHash));

    async function bootstrap() {
      if (!auth.token) { ready.value = true; return; }
      try {
        state.user = await api.me();
        await loadHousehold();
      } catch { auth.clear(); state.user = null; }
      ready.value = true;
    }
    auth.onUnauthorized(() => { state.user = null; });
    bootstrap();

    function logout() {
      auth.clear();
      Object.assign(state, { user: null, household: null, products: [], recipes: [], loaded: { products: false, recipes: false } });
    }
    // Ключ роутера: перерисовываем экран при смене маршрута (включая параметры)
    const viewKey = computed(() => route.value.name + "/" + (route.value.param || "") + "?" + new URLSearchParams(route.value.query));
    const active = (p) => route.value.name === p || (p === "plan" && route.value.name === "day");
    return { route, ready, state, NAV, bootstrap, logout, viewKey, active };
  },
  template: `
    <div v-if="!ready" class="boot">Загрузка…</div>
    <LoginView v-else-if="!state.user" @done="bootstrap" />
    <div v-else class="layout">
      <nav class="sidebar">
        <div class="brand">🥗 Food Tracker</div>
        <a v-for="n in NAV" :key="n.path" :href="'#/' + n.path" class="nav-link" :class="{ active: active(n.path) }">
          <span class="nav-icon">{{ n.icon }}</span>{{ n.label }}</a>
        <div class="sidebar-foot small muted">{{ state.user.username }}<div class="tiny" v-if="state.household">{{ state.household.name }}</div></div>
      </nav>
      <main class="main">
        <PlannerView v-if="route.name === 'plan'" :key="viewKey" :query="route.query" />
        <DayView v-else-if="route.name === 'day'" :key="viewKey" :date="route.param" />
        <ShoppingView v-else-if="route.name === 'shopping'" :key="'shopping'" :query="route.query" />
        <FridgeView v-else-if="route.name === 'fridge'" />
        <RecipesView v-else-if="route.name === 'recipes'" />
        <CatalogView v-else-if="route.name === 'catalog'" />
        <FamilyView v-else-if="route.name === 'family' || route.name === 'profile'" @logout="logout" />
        <div v-else class="empty">Страница не найдена. <a href="#/plan">К плану</a></div>
      </main>
      <nav class="tabbar">
        <a v-for="n in NAV" :key="n.path" :href="'#/' + n.path" :class="{ active: active(n.path) }">
          <span class="nav-icon">{{ n.icon }}</span>{{ n.label }}</a>
      </nav>
    </div>
    <div class="toasts"><div v-for="t in state.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div></div>`,
};

createApp(App).mount("#app");
