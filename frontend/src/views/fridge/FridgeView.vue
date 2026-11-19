<script setup lang="ts">
// Холодильник: готовое (кастрюли и морозилка), продукты (запасы), архив доеденного и выброшенного.
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { ensureCatalog, recipeById } from "../../catalog";
import CookModal from "../../components/fridge/CookModal.vue";
import PotModal from "../../components/fridge/PotModal.vue";
import { toastError } from "../../session";
import { dayMonth, fmt, grams, local, num, today } from "../../util";

// вкладка «Продукты» — отдельным куском: открывают её реже, чем «Готовое»
const StockTab = defineAsyncComponent(() => import("../../components/stock/StockTab.vue"));

type Pot = Schemas["RecipeCookingLogResponse"];
type Tab = "active" | "stock" | "archive";
const tab = ref<Tab>(local.get<Tab>("ft.fridgeTab", "active"));
watch(tab, (t) => local.set("ft.fridgeTab", t));
const pots = ref<Pot[]>([]);
const archive = ref<Schemas["PotArchiveItem"][]>([]);
const costs = ref<Record<number, Schemas["PotCost"]>>({});
const cooking = ref(false);
const opened = ref<Pot | null>(null);
const stockKey = ref(0);
const todayIso = today();

async function load() {
  try {
    await ensureCatalog();
    [pots.value, archive.value] = await Promise.all([
      ok(api.GET("/api/v1/recipes/cooking-logs")),
      ok(api.GET("/api/v1/recipes/cooking-logs/archive", { params: { query: { include_deleted: true } } })),
    ]);
  } catch (e) { toastError(e); }
  try { costs.value = Object.fromEntries((await ok(api.GET("/api/v1/finance/pot-costs"))).map((c) => [c.pot_id, c])); } catch { /* себестоимость необязательна */ }
}
onMounted(load);
function onSaved() { cooking.value = false; opened.value = null; stockKey.value++; load(); }

const potName = (p: { recipe_id?: number | null; recipe_name?: string | null }) =>
  (p.recipe_id ? recipeById.value[p.recipe_id]?.name : undefined) || p.recipe_name || (p.recipe_id ? `Рецепт #${p.recipe_id}` : "Рецепт удалён");
function bar(p: Pot) {
  const total = num(p.total_cooked_weight) || 1;
  const rem = num(p.current_remaining_weight);
  const planned = Math.min(num(p.planned_g), rem);
  return { rem: (rem / total) * 100, planned: (planned / total) * 100, plannedLeft: ((rem - planned) / total) * 100, free: rem - num(p.planned_g) };
}
const groups = computed(() => [
  { key: "fridge", title: "", list: pots.value.filter((p) => !p.is_frozen) },
  { key: "freezer", title: "Морозилка — заготовки", list: pots.value.filter((p) => p.is_frozen) },
].filter((g) => g.list.length));
const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
</script>

<template>
  <div class="fridge">
    <header class="head">
      <h1 class="display">Холодильник</h1>
      <button class="fill" @click="cooking = true">Приготовить</button>
    </header>
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'active'" :class="{ on: tab === 'active' }" @click="tab = 'active'">Готовое · {{ pots.length }}</button>
      <button role="tab" :aria-selected="tab === 'stock'" :class="{ on: tab === 'stock' }" @click="tab = 'stock'">Продукты</button>
      <button role="tab" :aria-selected="tab === 'archive'" :class="{ on: tab === 'archive' }" @click="tab = 'archive'">Архив</button>
    </div>

    <template v-if="tab === 'active'">
      <div v-if="!pots.length" class="empty">
        <p>Холодильник пуст. Приготовьте блюдо — и планы по нему сами перейдут в «есть в холодильнике».</p>
        <button class="fill" @click="cooking = true">Приготовить</button>
      </div>
      <section v-for="g in groups" :key="g.key" class="group">
        <h2 v-if="g.title">❄️ {{ g.title }}</h2>
        <button v-for="p in g.list" :key="p.id" class="pot-row" :class="{ frozen: p.is_frozen }" @click="opened = p">
          <span class="top">
            <b class="name">{{ potName(p) }}</b>
            <span class="w"><b>{{ grams(p.current_remaining_weight) }}</b> <span class="muted">из {{ grams(p.total_cooked_weight) }}</span></span>
          </span>
          <span class="gauge" :title="'Запланировано ' + grams(p.planned_g)">
            <i :style="{ width: bar(p).rem + '%' }"></i>
            <s :style="{ left: bar(p).plannedLeft + '%', width: bar(p).planned + '%' }"></s>
          </span>
          <span class="meta small muted">
            <span>{{ when(p.cooked_at) }}<template v-if="p.good_until"> · <span :class="{ late: p.good_until < todayIso }">{{ p.is_frozen ? "годно" : "съесть" }} до {{ dayMonth(p.good_until) }}</span></template>
              · {{ fmt(p.calories_per_100g) }} ккал/100 г<template v-if="costs[p.id]?.cost"> · {{ fmt(costs[p.id].cost) }} ₽{{ costs[p.id].complete ? "" : "+" }}</template></span>
            <span v-if="bar(p).free >= 0">свободно {{ grams(bar(p).free) }} · в планах {{ grams(p.planned_g) }}</span>
            <span v-else class="late">в планах на {{ grams(-bar(p).free) }} больше, чем осталось</span>
          </span>
        </button>
      </section>
    </template>

    <StockTab v-else-if="tab === 'stock'" :key="stockKey" />

    <template v-else>
      <p v-if="!archive.length" class="muted">Архив пуст.</p>
      <div v-for="a in archive" :key="a.id" class="arch">
        <div class="top"><b>{{ a.recipe_name || potName(a) }}</b>
          <span class="badge" :class="a.is_discarded ? 'bad' : 'ok'">{{ a.is_discarded ? "выброшено" : "доедено" }}</span></div>
        <div class="small muted">{{ when(a.cooked_at) }} · {{ grams(a.total_cooked_weight) }} · {{ fmt(a.calories_per_100g) }} ккал/100 г</div>
        <ul v-if="a.events?.length" class="small"><li v-for="(ev, i) in a.events" :key="i">{{ ev }}</li></ul>
      </div>
    </template>

    <CookModal v-if="cooking" @close="cooking = false" @saved="onSaved" />
    <PotModal v-if="opened" :pot="opened" :name="potName(opened)" @close="opened = null" @saved="onSaved" />
  </div>
</template>

<style scoped>
.fridge { display: flex; flex-direction: column; gap: 14px; max-width: 900px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
h1 { font-size: 32px; color: var(--rim); }
.tabs { display: inline-flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); align-self: flex-start; }
.tabs button { min-height: 40px; border: 0; padding: 0 16px; color: var(--ink); font-weight: 500; }
.tabs button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
.empty { display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding: 18px; border-radius: var(--r-pot);
  background: var(--enamel); border: 1.5px solid var(--line); }
.empty p { margin: 0; }
.group { display: flex; flex-direction: column; gap: 8px; }
.group h2 { font-size: 18px; margin-top: 6px; }
/* кастрюля — эмалированная плашка, остаток — «уровень» внутри; запланированное — штриховкой */
.pot-row {
  display: flex; flex-direction: column; align-items: stretch; gap: 8px; width: 100%; min-height: 0; padding: 14px 16px;
  text-align: left; font-weight: 400; color: var(--ink); background: var(--enamel); border: 1.5px solid var(--line); border-radius: var(--r-pot);
}
.pot-row:hover { border-color: var(--rim); }
.pot-row.frozen { border-style: dashed; border-color: var(--sky); }
.top { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.name { font-size: 16px; }
.w { white-space: nowrap; }
.gauge { position: relative; height: 10px; border-radius: 999px; background: var(--enamel-2); overflow: hidden; border: 1px solid var(--line); }
.gauge i { position: absolute; left: 0; top: 0; bottom: 0; background: var(--rim); }
.frozen .gauge i { background: var(--sky); }
.gauge s { position: absolute; top: 0; bottom: 0; opacity: 0.85;
  background: repeating-linear-gradient(45deg, var(--beak) 0 4px, transparent 4px 7px); }
.meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 2px 12px; }
.late { color: var(--tomato); }
.arch { padding: 12px 16px; border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); }
.arch ul { margin: 6px 0 0; padding-left: 18px; }
.badge { font-size: 12px; padding: 2px 10px; border-radius: 999px; }
.badge.ok { background: var(--rim-soft); color: var(--rim); }
.badge.bad { background: var(--beak-soft); color: var(--tomato); }
</style>
