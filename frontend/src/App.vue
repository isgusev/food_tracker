<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { authRedirect } from "./router";
import { auth } from "./api/client";
import NavIcon from "./components/NavIcon.vue";
import { MORE } from "./nav";
import { loadSession, session } from "./session";

const route = useRoute();
const router = useRouter();
// Пока переезжаем: перенесённые экраны — новый интерфейс, остальное — старый на /app/ (вход общий).
// На телефоне внизу пять пунктов, остальные разделы — в «Ещё»; на компьютере слева все сразу.
type Nav = { to: string; label: string; icon: InstanceType<typeof NavIcon>["$props"]["name"]; next?: boolean; place: "both" | "desk" | "phone" };
const NAV: Nav[] = [
  { to: "/today", label: "Сегодня", icon: "today", next: true, place: "both" },
  { to: "/plan", label: "План", icon: "plan", next: true, place: "both" },
  { to: "/shopping", label: "Покупки", icon: "shop", next: true, place: "both" },
  { to: "/fridge", label: "Холодильник", icon: "fridge", next: true, place: "both" },
  ...MORE.map((m) => ({ ...m, place: "desk" as const })),
  { to: "/more", label: "Ещё", icon: "more", next: true, place: "phone" },
];

// «Ещё» подсвечен и на разделах из него (рецепты и т. д.)
const inMore = computed(() => MORE.some((m) => route.path.startsWith(m.to)));

auth.onUnauthorized(() => router.replace("/login"));
onMounted(async () => {
  await Promise.all([loadSession(), router.isReady()]);
  const to = authRedirect(route);     // первый переход был до загрузки сессии — проверяем ещё раз
  if (to) router.replace(to);
});
</script>

<template>
  <div v-if="!session.ready" class="boot muted">Загрузка…</div>
  <div v-else-if="!session.user || route.meta.public" class="bare"><RouterView /></div>
  <div v-else class="shell">
    <nav class="rail" aria-label="Разделы">
      <div class="brand display">ЕлиГуси</div>
      <template v-for="n in NAV" :key="n.to">
        <RouterLink v-if="n.next" :to="n.to" class="nav-link" :class="[n.place, { on: n.to === '/more' && inMore }]" active-class="on"><NavIcon :name="n.icon" />{{ n.label }}</RouterLink>
        <a v-else :href="n.to" class="nav-link" :class="n.place"><NavIcon :name="n.icon" />{{ n.label }}</a>
      </template>
    </nav>
    <main class="main"><RouterView /></main>
  </div>
  <div class="toasts" aria-live="polite">
    <div v-for="t in session.toasts" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
  </div>
</template>

<style scoped>
.boot { padding: 40px var(--gutter); }
.shell { min-height: 100vh; display: grid; grid-template-columns: 1fr; }
.main { padding: 20px var(--gutter) calc(96px + env(safe-area-inset-bottom)); min-width: 0; }
.rail {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 30; display: flex;
  background: var(--enamel); border-top: 2px solid var(--rim);
  padding: 4px 4px calc(4px + env(safe-area-inset-bottom));
}
.brand { display: none; }
.nav-link {
  flex: 1; min-width: 0; min-height: 52px; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 2px; font-size: 11px; color: var(--muted); text-decoration: none; border-radius: var(--r-in);
}
.nav-link.on { color: var(--rim); font-weight: 700; }
.nav-link.desk { display: none; }
@media (min-width: 900px) {
  .shell { grid-template-columns: 220px 1fr; }
  .main { padding: 28px 32px 48px; }
  .rail {
    position: sticky; top: 0; height: 100vh; flex-direction: column; gap: 2px; align-self: start;
    border-top: 0; border-right: 2px solid var(--rim); padding: 20px 12px;
  }
  .brand { display: block; font-size: 20px; color: var(--rim); padding: 4px 12px 18px; }
  .nav-link { flex: none; flex-direction: row; justify-content: flex-start; gap: 10px; font-size: 15px; padding: 0 12px; min-height: 44px; }
  .nav-link.on { background: var(--rim-soft); }
  .nav-link.desk { display: flex; }
  .nav-link.phone { display: none; }
}
</style>
