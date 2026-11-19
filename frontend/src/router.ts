import { createRouter, createWebHashHistory, type RouteLocationNormalized } from "vue-router";
import { session, toast } from "./session";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/today" },
    { path: "/today", component: () => import("./views/TodayView.vue"), meta: { title: "Сегодня" } },
    { path: "/plan", component: () => import("./views/plan/PlanView.vue"), meta: { title: "План" } },
    { path: "/day/:date(\\d{4}-\\d{2}-\\d{2})", component: () => import("./views/plan/DayView.vue"), props: true, meta: { title: "День" } },
    { path: "/shopping", component: () => import("./views/shopping/ShoppingView.vue"), meta: { title: "Покупки" } },
    { path: "/recipes", component: () => import("./views/recipes/RecipesView.vue"), meta: { title: "Рецепты" } },
    { path: "/catalog", component: () => import("./views/catalog/CatalogView.vue"), meta: { title: "Продукты" } },
    { path: "/money", component: () => import("./views/money/MoneyView.vue"), meta: { title: "Деньги" } },
    { path: "/family", component: () => import("./views/family/FamilyView.vue"), meta: { title: "Семья" } },
    { path: "/fridge", component: () => import("./views/fridge/FridgeView.vue"), meta: { title: "Холодильник" } },
    { path: "/more", component: () => import("./views/MoreView.vue"), meta: { title: "Ещё" } },
    { path: "/login", component: () => import("./views/LoginView.vue"), meta: { public: true } },
    { path: "/register", component: () => import("./views/LoginView.vue"), meta: { public: true } },
    { path: "/:rest(.*)*", redirect: "/today" },
  ],
});

/** Куда увести с этой страницы по состоянию входа (null — остаться). Зовётся и после загрузки сессии в App. */
export function authRedirect(to: RouteLocationNormalized): string | null {
  if (session.ready && !session.user && !to.meta.public) return "/login";
  if (session.user && (to.path === "/login" || to.path === "/register")) {
    // ссылку-приглашение открыли, уже войдя: она для нового пользователя — не «страница не найдена», а пояснение
    if (to.query.code) toast("Вы уже вошли. Приглашение — для нового пользователя: откройте ссылку на его устройстве или выйдите.", "info", 7000);
    return "/today";
  }
  return null;
}
router.beforeEach((to) => authRedirect(to) ?? true);
