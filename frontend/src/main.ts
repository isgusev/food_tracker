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

createApp(App).use(router).mount("#app");
