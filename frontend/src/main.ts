import "@fontsource-variable/golos-text";
import "@fontsource-variable/unbounded";
import "./styles/tokens.css";
import "./styles/base.css";
import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";

// тема — та же настройка, что в старом интерфейсе (Семья → Тема)
try {
  const theme = JSON.parse(localStorage.getItem("ft.theme") || '"auto"');
  if (theme === "light" || theme === "dark") document.documentElement.setAttribute("data-theme", theme);
} catch { /* нет хранилища */ }

// После деплоя у открытой страницы старые куски кода (с прежним хешем) уже удалены — подгрузка падает.
// Перезагружаем страницу один раз (не чаще раза в 10 с, чтобы не зациклиться, если сервер недоступен).
function reloadForNewVersion(): void {
  const key = "ft.reloadedForChunk";
  let last = 0;
  try { last = Number(sessionStorage.getItem(key) || 0); } catch { /* нет хранилища */ }
  if (Date.now() - last < 10_000) return;
  try { sessionStorage.setItem(key, String(Date.now())); } catch { /* нет хранилища */ }
  location.reload();
}
const isChunkError = (err: unknown) =>
  /dynamically imported module|Importing a module script failed|error loading dynamically|Unable to preload CSS/i.test(String((err as Error)?.message ?? err));
window.addEventListener("vite:preloadError", (e) => { e.preventDefault(); reloadForNewVersion(); });
window.addEventListener("unhandledrejection", (e) => { if (isChunkError(e.reason)) reloadForNewVersion(); });
router.onError((err) => { if (isChunkError(err)) reloadForNewVersion(); });

const app = createApp(App);
// асинхронные компоненты (вкладки) падают сюда, а не в роутер
app.config.errorHandler = (err) => {
  if (isChunkError(err)) { reloadForNewVersion(); return; }
  console.error(err);
};
app.use(router).mount("#app");
