import { createRouter, createWebHashHistory } from "vue-router";
import { session } from "./session";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/today" },
    { path: "/today", component: () => import("./views/TodayView.vue"), meta: { title: "Сегодня" } },
    { path: "/plan", component: () => import("./views/plan/PlanView.vue"), meta: { title: "План" } },
    { path: "/day/:date(\\d{4}-\\d{2}-\\d{2})", component: () => import("./views/plan/DayView.vue"), props: true, meta: { title: "День" } },
    { path: "/fridge", component: () => import("./views/fridge/FridgeView.vue"), meta: { title: "Холодильник" } },
    { path: "/login", component: () => import("./views/LoginView.vue"), meta: { public: true } },
    { path: "/:rest(.*)*", redirect: "/today" },
  ],
});

router.beforeEach((to) => {
  if (session.ready && !session.user && !to.meta.public) return "/login";
  if (session.user && to.path === "/login") return "/today";
  return true;
});
