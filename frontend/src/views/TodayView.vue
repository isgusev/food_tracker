<script setup lang="ts">
// «Сегодня»: мой день (приёмы пищи, «Съел» одним касанием, КБЖУ) и семья (что готовить, кто что съел).
import { computed, onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../api/client";
import MealPot from "../components/MealPot.vue";
import { activeMembers, session, setViewMember, toast, toastError, viewMember } from "../session";
import { MEALS, addDays, currentMeal, dayMonth, fmt, grams, num, plural, today, weekday } from "../util";

type Item = Schemas["MealItemResponse"];
type Portion = Schemas["PortionResponse"];

const day = today();
const tomorrow = addDays(day, 1);
const items = ref<Item[]>([]);
const tomorrowItems = ref<Item[]>([]);
const loading = ref(true);
const busy = ref(false);
const nowMeal = currentMeal();

async function load() {
  try {
    [items.value, tomorrowItems.value] = await Promise.all([
      ok(api.GET("/api/v1/plan", { params: { query: { start_date: day, end_date: day } } })),
      ok(api.GET("/api/v1/plan", { params: { query: { start_date: tomorrow, end_date: tomorrow } } })),
    ]);
  } catch (e) { toastError(e); } finally { loading.value = false; }
}
onMounted(load);

/** Действие с сервером: занято → ответ → тост; ошибка — тостом. */
async function act<T>(fn: () => Promise<T>, msg?: string): Promise<T | undefined> {
  busy.value = true;
  try { const r = await fn(); if (msg) toast(msg); return r; }
  catch (e) { toastError(e); return undefined; }
  finally { busy.value = false; }
}
function replace(updated: Item) { items.value = items.value.map((i) => (i.id === updated.id ? updated : i)); }

const eat = (p: Portion) => act(async () => replace(await ok(api.POST("/api/v1/plan/portions/{portion_id}/eat",
  { params: { path: { portion_id: p.id } }, body: {} }))));
const uneat = (p: Portion) => act(async () => replace(await ok(api.POST("/api/v1/plan/portions/{portion_id}/uneat",
  { params: { path: { portion_id: p.id } } }))), "Отметка снята");
const accept = (it: Item) => act(async () => replace(await ok(api.POST("/api/v1/plan/{item_id}/accept",
  { params: { path: { item_id: it.id } } }))));

async function suggestToday() {
  const r = await act(() => ok(api.POST("/api/v1/plan/autofill", { body: { start: day, end: day } })));
  if (r) { toast(r.items.length ? `Предложено: ${r.items.length}` : "Нечего предложить: ячейки заняты или нет рецептов в ротации"); await load(); }
}

// ---- мой день
const memberId = computed(() => session.viewMemberId);
const byMeal = computed(() => Object.fromEntries(MEALS.map((m) => [m.key, items.value.filter((i) => i.meal_type === m.key)])));
const myPortions = computed(() => items.value.flatMap((i) => i.portions.filter((p) => p.member_id === memberId.value)));
const sum = (ps: Portion[], k: "calories" | "proteins" | "fats" | "carbs") => ps.reduce((s, p) => s + num(p[k]), 0);
const planned = computed(() => sum(myPortions.value, "calories"));
const eaten = computed(() => sum(myPortions.value.filter((p) => p.is_eaten), "calories"));
const target = computed(() => num(viewMember.value?.targets?.calories) || 2000);
const pct = (v: number) => `${Math.min(100, (v / target.value) * 100)}%`;
const macros = computed(() => ({
  p: sum(myPortions.value, "proteins"), f: sum(myPortions.value, "fats"), c: sum(myPortions.value, "carbs"),
  tp: num(viewMember.value?.targets?.proteins),
}));

// ---- семья
const cookToday = computed(() => {
  const by = new Map<number, { id: number; name: string; grams: number; meals: Set<string> }>();
  for (const it of items.value) {
    if (it.kind !== "recipe" || it.state !== "to_cook" || !it.recipe_id || num(it.remaining_weight_g) <= 0) continue;
    const r = by.get(it.recipe_id) ?? { id: it.recipe_id, name: it.name, grams: 0, meals: new Set<string>() };
    r.grams += num(it.remaining_weight_g);
    r.meals.add(it.meal_type);
    by.set(it.recipe_id, r);
  }
  return [...by.values()];
});
const cookTomorrow = computed(() => [...new Set(tomorrowItems.value
  .filter((i) => i.kind === "recipe" && i.state === "to_cook").map((i) => i.name))]);
const others = computed(() => activeMembers.value.filter((m) => m.id !== memberId.value).map((m) => {
  const ps = items.value.flatMap((i) => i.portions.filter((p) => p.member_id === m.id));
  return { m, planned: sum(ps, "calories"), eaten: sum(ps.filter((p) => p.is_eaten), "calories"), left: ps.filter((p) => !p.is_eaten).length };
}));
const drafts = computed(() => items.value.filter((i) => i.origin === "auto").length);

/** Сколько закладок нужно на сегодня: как в покупках — целыми, «можно половиной» — шагом 0,5. */
function batches(need: number, recipe: Schemas["RecipeResponse"]): number {
  const one = num(recipe.estimated_cooked_weight);
  if (one <= 0) return 1;
  const step = recipe.allow_half ? 0.5 : 1;
  return Math.max(step, Math.ceil(need / one / step - 1e-9) * step);
}

async function cook(r: { id: number; name: string; grams: number }) {
  const done = await act(async () => {
    const recipe = await ok(api.GET("/api/v1/recipes/{recipe_id}", { params: { path: { recipe_id: r.id } } }));
    const k = batches(r.grams, recipe);
    await ok(api.POST("/api/v1/recipes/{recipe_id}/cook", {
      params: { path: { recipe_id: r.id } },
      body: {
        total_cooked_weight: Math.round(num(recipe.estimated_cooked_weight) * k * 10) / 10,
        ingredients: (recipe.template_ingredients ?? []).map((i) => ({
          variant_id: i.variant_id, weight_g: Math.round(num(i.weight_g) * k * 10) / 10, exact: !!i.exact })),
      },
    }));
    return k;
  });
  if (done) {
    toast(`«${r.name}» — ${done === 1 ? "закладка" : `×${fmt(done)} закладки`} по рецепту, в холодильнике`);
    await load();
  }
}
</script>

<template>
  <div class="today">
    <header class="head">
      <div>
        <h1 class="display">Сегодня</h1>
        <p class="muted">{{ weekday(day) }}, {{ dayMonth(day) }}</p>
      </div>
      <div v-if="activeMembers.length > 1" class="who" role="group" aria-label="Чей день">
        <button v-for="m in activeMembers" :key="m.id" class="chip" :class="{ on: m.id === memberId }"
                :aria-pressed="m.id === memberId" @click="setViewMember(m.id)">{{ m.is_me ? "Я" : m.name }}</button>
      </div>
    </header>

    <div class="day-bar" :aria-label="`Съедено ${fmt(eaten)} из ${fmt(target)} ккал`">
      <div class="bar"><i class="plan" :style="{ width: pct(planned) }"></i><i class="ate" :style="{ width: pct(eaten) }"></i></div>
      <div class="row small">
        <span><b>{{ fmt(eaten) }}</b> съедено · в плане {{ fmt(planned) }} из {{ fmt(target) }} ккал</span>
        <span class="muted">Б {{ fmt(macros.p) }}<template v-if="macros.tp"> / {{ fmt(macros.tp) }}</template> · Ж {{ fmt(macros.f) }} · У {{ fmt(macros.c) }}</span>
      </div>
    </div>

    <p v-if="loading" class="muted">Загрузка…</p>
    <template v-else>
      <div v-if="!items.length" class="pot empty-day">
        <p>На сегодня ничего не запланировано.</p>
        <button class="fill" :disabled="busy" @click="suggestToday">Предложить на сегодня</button>
      </div>
      <div v-else class="meals">
        <MealPot v-for="m in MEALS" :key="m.key" :label="m.label" :items="byMeal[m.key]" :member-id="memberId"
                 :now="m.key === nowMeal" :busy="busy" @eat="eat" @uneat="uneat" @accept="accept" />
      </div>

      <section class="family">
        <h2>Семья</h2>
        <div v-if="cookToday.length" class="inset block">
          <h3>Приготовить сегодня</h3>
          <div v-for="r in cookToday" :key="r.id" class="line">
            <div class="grow"><b>{{ r.name }}</b>
              <div class="small muted">нужно {{ grams(r.grams) }} · {{ [...r.meals].map((k) => MEALS.find((x) => x.key === k)?.label.toLowerCase()).join(", ") }}</div></div>
            <button :disabled="busy" @click="cook(r)" title="По рецепту, столько закладок, сколько нужно на сегодня; другой состав — в «Холодильнике»">Приготовить</button>
          </div>
        </div>
        <div v-if="cookTomorrow.length" class="inset block">
          <h3>Завтра</h3>
          <p class="small">Готовить: {{ cookTomorrow.join(", ") }}. <a href="/app/#/shopping">Проверить покупки</a></p>
        </div>
        <div v-if="others.length" class="inset block">
          <h3>Остальные</h3>
          <button v-for="o in others" :key="o.m.id" class="line person" @click="setViewMember(o.m.id)">
            <span class="grow">{{ o.m.name }}</span>
            <span class="small muted">{{ fmt(o.eaten) }} из {{ fmt(o.planned) }} ккал<template v-if="o.left"> · не отмечено {{ o.left }}</template></span>
          </button>
        </div>
        <p v-if="drafts" class="small muted">
          {{ drafts }} {{ plural(drafts, "предложение", "предложения", "предложений") }} автоплана на сегодня — «Принять» или поправьте в
          <RouterLink to="/plan">плане</RouterLink>.
        </p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.today { max-width: 760px; display: flex; flex-direction: column; gap: 18px; }
.head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px; }
h1 { font-size: 32px; color: var(--rim); }
.head p { margin: 4px 0 0; }
.who { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { min-height: 40px; padding: 0 14px; border-color: var(--line); color: var(--ink); font-weight: 500; }
.chip.on { background: var(--rim); border-color: var(--rim); color: var(--on-fill); font-weight: 700; }
.day-bar { display: flex; flex-direction: column; gap: 8px; }
.bar { position: relative; height: 10px; border-radius: 999px; background: var(--enamel-2); overflow: hidden; border: 1px solid var(--line); }
.bar i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; }
.bar .plan { background: var(--rim-soft); }
.bar .ate { background: var(--rim); }
.row { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; }
.meals { display: flex; flex-direction: column; gap: 12px; }
.empty-day { padding: 20px; display: flex; flex-direction: column; align-items: flex-start; gap: 12px; }
.empty-day p { margin: 0; }
.family { display: flex; flex-direction: column; gap: 10px; }
.family h2 { font-size: 20px; margin-top: 6px; }
.block { padding: 12px 14px; }
h3 { font-size: 15px; margin-bottom: 6px; }
.block p { margin: 0; }
.line { display: flex; align-items: center; gap: 12px; padding: 8px 0; }
.line + .line { border-top: 1px solid var(--line); }
.grow { flex: 1; min-width: 0; }
.person { width: 100%; border: 0; border-radius: 0; min-height: 44px; padding: 8px 0; color: var(--ink); font-weight: 500; text-align: left; }
</style>
