<script setup lang="ts">
// План семьи на неделю: 7 дней × 4 приёма пищи, автоплан (✨, черновик «карандашом»), перенос блюд мышью.
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api, ok } from "../../api/client";
import { ensureCatalog } from "../../catalog";
import AddItemModal from "../../components/plan/AddItemModal.vue";
import MemberSwitch from "../../components/plan/MemberSwitch.vue";
import PlanEntry from "../../components/plan/PlanEntry.vue";
import PlanItemModal from "../../components/plan/PlanItemModal.vue";
import TemplatesModal from "../../components/plan/TemplatesModal.vue";
import { allEaten, isLooseDraft, memberMacros, type Item } from "../../plan";
import { hasTargets, session, targetsForMeters, toast, toastError, viewMember } from "../../session";
import {
  MEALS, MEAL_ORDER, addDays, dayMonthShort, dayNum, fmt, local, monthOf, num, plural, range, startOfWeek, today, weekdayShort,
} from "../../util";

const route = useRoute();
const todayIso = today();
const weekStart = ref(startOfWeek(String(route.query.week || local.get("ft.week", todayIso))));
const weekEnd = computed(() => addDays(weekStart.value, 6));
const days = computed(() => range(weekStart.value, weekEnd.value));
const items = ref<Item[]>([]);
const loading = ref(false);
const busy = ref(false);
const suggesting = ref("");
const adding = ref<{ date: string; meal: string } | null>(null);
const opened = ref<Item | null>(null);
const templates = ref(false);

async function load() {
  loading.value = true;
  try {
    await ensureCatalog();
    items.value = await ok(api.GET("/api/v1/plan", { params: { query: { start_date: weekStart.value, end_date: weekEnd.value } } }));
  } catch (e) { toastError(e); } finally { loading.value = false; }
}
watch(weekStart, (w) => { local.set("ft.week", w); load(); });
onMounted(load);

/** Действие с сервером: занято, тост, перезагрузка недели. */
async function act(fn: () => Promise<unknown>, msg?: string) {
  busy.value = true;
  try { await fn(); if (msg) toast(msg); await load(); }
  catch (e) { toastError(e); }
  finally { busy.value = false; }
}

// ---- автоплан
const firstOpen = computed(() => (weekStart.value < todayIso ? todayIso : weekStart.value));
async function suggest(start: string, end: string, key: string, cook = true) {
  suggesting.value = key;
  try {
    const r = await ok(api.POST("/api/v1/plan/autofill", { body: { start, end, cook } }));
    toast(r.items.length
      ? `Предложено блюд: ${r.items.length}${r.replaced ? ` (прежних предложений заменено: ${r.replaced})` : ""}. Правьте или принимайте`
      : "Нечего предложить: ячейки заняты или нет рецептов в ротации");
    await load();
  } catch (e) { toastError(e); } finally { suggesting.value = ""; }
}
const drafts = computed(() => items.value.filter((i) => i.origin === "auto"));
const loose = computed(() => items.value.filter(isLooseDraft));
const acceptAll = () => act(() => ok(api.POST("/api/v1/plan/accept", { body: { start: weekStart.value, end: weekEnd.value } })),
  "Предложения приняты — теперь это обычный план");
async function clearDrafts() {
  if (!confirm(`Убрать предложения без 📌 (${loose.value.length})?`)) return;
  await act(async () => { for (const it of loose.value) await ok(api.DELETE("/api/v1/plan/{item_id}", { params: { path: { item_id: it.id } } })); },
    "Предложения убраны");
}
const accept = (it: Item) => act(() => ok(api.POST("/api/v1/plan/{item_id}/accept", { params: { path: { item_id: it.id } } })));
const pin = (it: Item) => act(() => ok(api.PATCH("/api/v1/plan/{item_id}", { params: { path: { item_id: it.id } }, body: { pinned: !it.pinned } })),
  it.pinned ? "Откреплено" : "Закреплено — новый подбор не заменит");
const swap = (it: Item) => act(() => ok(api.POST("/api/v1/plan/{item_id}/alternative", { params: { path: { item_id: it.id } } })));
const remove = (it: Item) => act(() => ok(api.DELETE("/api/v1/plan/{item_id}", { params: { path: { item_id: it.id } } })));

// ---- перенос мышью на другой день / приём
const dragId = ref<number | null>(null);
const dropTarget = ref("");
function dragStart(it: Item, e: DragEvent) { dragId.value = it.id; if (e.dataTransfer) e.dataTransfer.effectAllowed = "move"; }
async function dropTo(d: string, meal: string) {
  const id = dragId.value;
  dragId.value = null; dropTarget.value = "";
  const it = items.value.find((x) => x.id === id);
  if (!it || (it.date_day === d && it.meal_type === meal)) return;
  await act(() => ok(api.PATCH("/api/v1/plan/{item_id}", { params: { path: { item_id: it.id } }, body: { date_day: d, meal_type: meal } })));
}

// ---- прошлая неделя
async function copyPrevWeek() {
  try {
    const src = await ok(api.GET("/api/v1/plan", { params: { query: { start_date: addDays(weekStart.value, -7), end_date: addDays(weekStart.value, -1) } } }));
    if (!src.length) { toast("На прошлой неделе нет блюд"); return; }
    if (!confirm(`Скопировать ${src.length} блюд с прошлой недели (с теми же порциями)?` +
      (items.value.length ? `\nНа этой неделе уже есть ${items.value.length} — они останутся.` : ""))) return;
    await act(async () => {
      for (const it of src) {
        if (!it.recipe_id && !it.variant_id) continue;   // рецепт удалён — копировать нечего
        await ok(api.POST("/api/v1/plan", { body: {
          date_day: addDays(it.date_day, 7), meal_type: it.meal_type,
          ...(it.kind === "product" ? { variant_id: it.variant_id, exact: !!it.exact } : { recipe_id: it.recipe_id }),
          portions: it.portions.map((p) => ({ member_id: p.member_id, weight_g: num(p.weight_g) })),
        } }));
      }
    }, "План скопирован");
  } catch (e) { toastError(e); }
}

// ---- сводка
const memberId = computed(() => session.viewMemberId);
const memberName = computed(() => viewMember.value?.name ?? "вас");
const targets = computed(() => targetsForMeters(viewMember.value));
const byDay = computed(() => {
  const map: Record<string, Record<string, Item[]>> = {};
  for (const d of days.value) map[d] = Object.fromEntries(MEALS.map((m) => [m.key, [] as Item[]]));
  for (const it of [...items.value].sort((a, b) => MEAL_ORDER[a.meal_type] - MEAL_ORDER[b.meal_type] || a.id - b.id))
    map[it.date_day]?.[it.meal_type]?.push(it);
  return map;
});
const dayInfo = computed(() => Object.fromEntries(days.value.map((d) => {
  const list = items.value.filter((i) => i.date_day === d);
  const all = memberMacros(list, memberId.value);
  return [d, { all, eaten: memberMacros(list, memberId.value, true).calories, pct: Math.min(100, (all.calories / (targets.value.calories || 1)) * 100) }];
})));
const stats = computed(() => {
  const open = items.value.filter((it) => !allEaten(it));
  return {
    total: items.value.length,
    toCook: new Set(open.filter((it) => it.state === "to_cook").map((it) => it.recipe_id)).size,
    products: open.filter((it) => it.kind === "product").length,
    avg: memberMacros(items.value, memberId.value).calories / 7,
  };
});
const shopHref = computed(() => {
  const start = weekStart.value < todayIso && weekEnd.value >= todayIso ? todayIso : weekStart.value;
  return `/app/#/shopping?start=${start}&end=${weekEnd.value}`;
});
const isCurrent = computed(() => weekStart.value <= todayIso && weekEnd.value >= todayIso);
</script>

<template>
  <div class="plan">
    <header class="head">
      <h1 class="display">План</h1>
      <div class="weeknav">
        <button class="text icon" aria-label="Предыдущая неделя" @click="weekStart = addDays(weekStart, -7)">‹</button>
        <span class="range">{{ dayMonthShort(weekStart) }} — {{ dayMonthShort(weekEnd) }}</span>
        <button class="text icon" aria-label="Следующая неделя" @click="weekStart = addDays(weekStart, 7)">›</button>
        <button v-if="!isCurrent" class="text small" @click="weekStart = startOfWeek(todayIso)">Текущая</button>
      </div>
    </header>

    <div class="tools">
      <button class="fill" :disabled="!!suggesting || weekEnd < todayIso" @click="suggest(firstOpen, weekEnd, 'week')"
              title="Заполнить пустые приёмы пищи: остатки, заготовки, затем готовки из рецептов в ротации. Ваш план не трогается">
        ✨ {{ suggesting === "week" ? "Подбираю…" : "Предложить неделю" }}</button>
      <button :disabled="!!suggesting || weekEnd < todayIso" title="Только остатки из холодильника и заготовки — без новых готовок"
              @click="suggest(firstOpen, weekEnd, 'fridge', false)">Только остатки</button>
      <button @click="copyPrevWeek">Прошлая неделя</button>
      <button @click="templates = true">Шаблоны</button>
      <a class="btn" :href="shopHref">Покупки на неделю</a>
    </div>

    <div v-if="drafts.length" class="draft-bar" role="status">
      <span class="swatch" aria-hidden="true"></span>
      <div class="grow">
        <b>Черновик: {{ drafts.length }} {{ plural(drafts.length, "предложение", "предложения", "предложений") }}</b>
        <div class="small muted">Карандашом — предложения планировщика. Правка, ✓ или «Принять всё» делают блюдо обычным; 📌 — оставить при новом подборе.</div>
      </div>
      <button v-if="loose.length" class="text" :disabled="busy" @click="clearDrafts">Убрать</button>
      <button class="fill" :disabled="busy" @click="acceptAll">✓ Принять всё</button>
    </div>

    <div class="stats small">
      <MemberSwitch />
      <span class="muted">Блюд <b>{{ stats.total }}</b> · приготовить <b>{{ stats.toCook }}</b> · купить готовым <b>{{ stats.products }}</b></span>
      <span v-if="viewMember" class="muted">{{ viewMember.name }} в среднем <b>{{ fmt(stats.avg) }}</b> ккал/день<template v-if="hasTargets(viewMember)"> (цель {{ fmt(targets.calories) }})</template></span>
      <span v-if="loading" class="muted">Загрузка…</span>
    </div>

    <div class="week">
      <section v-for="d in days" :key="d" class="day" :class="{ today: d === todayIso, past: d < todayIso }">
        <header class="day-head">
          <RouterLink :to="'/day/' + d" class="date" :aria-label="'Открыть день ' + dayMonthShort(d)">
            <span class="num display">{{ dayNum(d) }}</span>
            <span class="word"><b>{{ weekdayShort(d) }}</b><span>{{ d === todayIso ? "сегодня" : monthOf(d) }}</span></span>
          </RouterLink>
          <button v-if="d >= todayIso" class="day-suggest" :disabled="!!suggesting" :aria-label="'Предложить на ' + dayMonthShort(d)"
                  title="Предложить на этот день" @click="suggest(d, d, d)">{{ suggesting === d ? "…" : "✨" }}</button>
        </header>
        <div class="day-meter">
          <div class="bar"><i :class="{ over: dayInfo[d].all.calories > targets.calories * 1.1 }" :style="{ width: dayInfo[d].pct + '%' }"></i></div>
          <div class="tiny muted"><b class="kcal">{{ fmt(dayInfo[d].all.calories) }}</b> ккал · Б {{ fmt(dayInfo[d].all.proteins) }} · Ж {{ fmt(dayInfo[d].all.fats) }} · У {{ fmt(dayInfo[d].all.carbs) }}
            <span v-if="dayInfo[d].eaten"> · съедено {{ fmt(dayInfo[d].eaten) }}</span></div>
        </div>
        <div v-for="m in MEALS" :key="m.key" class="meal" :class="{ 'drop-on': dropTarget === d + m.key }"
             @dragover.prevent="dropTarget = d + m.key" @dragleave="dropTarget === d + m.key && (dropTarget = '')" @drop.prevent="dropTo(d, m.key)">
          <div class="meal-head">
            <span>{{ m.label }}</span>
            <button class="add" :aria-label="'Добавить: ' + m.label + ', ' + dayMonthShort(d)" @click="adding = { date: d, meal: m.key }">+</button>
          </div>
          <PlanEntry v-for="it in byDay[d][m.key]" :key="it.id" :item="it" :member-id="memberId" :member-name="memberName"
                     :busy="busy" :dragging="dragId === it.id" @open="opened = it" @accept="accept(it)" @pin="pin(it)" @swap="swap(it)"
                     @remove="remove(it)" @dragstart="dragStart(it, $event)" @dragend="dragId = null; dropTarget = ''" />
        </div>
      </section>
    </div>

    <AddItemModal v-if="adding" :date="adding.date" :meal="adding.meal" :days="days" @close="adding = null" @saved="adding = null; load()" />
    <PlanItemModal v-if="opened" :item="opened" @close="opened = null; load()" />
    <TemplatesModal v-if="templates" :week-start="weekStart" @close="templates = false" @applied="templates = false; load()" />
  </div>
</template>

<style scoped>
.plan { display: flex; flex-direction: column; gap: 14px; }
.head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; }
h1 { font-size: 32px; color: var(--rim); }
.weeknav { display: flex; align-items: center; gap: 2px; }
.icon { min-width: 44px; padding: 0; font-size: 20px; }
.range { min-width: 140px; text-align: center; font-weight: 600; }
.tools { display: flex; flex-wrap: wrap; gap: 8px; }
/* телефон: инструменты — одним рядом с прокруткой, неделя видна сразу */
@media (max-width: 640px) {
  .tools { flex-wrap: nowrap; overflow-x: auto; margin: 0 calc(-1 * var(--gutter)); padding: 0 var(--gutter) 4px; scrollbar-width: none; }
  .tools > * { flex: none; min-height: 40px; font-size: 14px; padding: 0 14px; }
  .weeknav { width: 100%; justify-content: space-between; }
}
.draft-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 10px 14px; border-radius: var(--r-pot);
  border: 1px dashed var(--graphite); background: var(--graphite-soft); }
.swatch { width: 26px; height: 26px; flex: none; border-radius: 7px; border: 1.5px dashed var(--graphite);
  background: repeating-linear-gradient(-45deg, transparent 0 4px, var(--graphite-soft) 4px 5px), var(--enamel); }
.grow { flex: 1; min-width: 200px; }
.stats { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px; }
.week { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 10px; align-items: start; }
@media (max-width: 1400px) { .week { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 1100px) { .week { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .week { grid-template-columns: 1fr; } }
.day { background: var(--enamel); border: 1.5px solid var(--line); border-radius: var(--r-pot); min-width: 0; }
/* ободок — у сегодняшнего дня: главное на экране */
.day.today { border: 2px solid var(--rim); }
.day.past { opacity: 0.8; }
.day-head { display: flex; align-items: center; gap: 8px; padding: 10px 10px 2px 14px; }
.date { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 0; color: inherit; text-decoration: none; }
.num { font-size: 30px; font-weight: 300; }
.today .num { color: var(--rim); font-weight: 500; }
.word { display: flex; flex-direction: column; line-height: 1.15; font-size: 13px; }
.word span { color: var(--muted); font-size: 12px; }
.day-suggest { min-height: 36px; min-width: 40px; padding: 0; border: 1px dashed var(--graphite); color: var(--graphite); }
.day-meter { padding: 4px 14px 8px; border-bottom: 1px solid var(--line); display: flex; flex-direction: column; gap: 4px; }
.bar { height: 6px; border-radius: 999px; background: var(--enamel-2); overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--rim); border-radius: 999px; }
.bar i.over { background: var(--tomato); }
.kcal { color: var(--ink); }
.meal { padding: 6px 10px 8px; }
.meal + .meal { border-top: 1px solid var(--enamel-2); }
.meal.drop-on { background: var(--rim-soft); border-radius: var(--r-in); }
.meal-head { display: flex; justify-content: space-between; align-items: center; font-size: 12px; color: var(--muted); font-weight: 600; }
.add { min-height: 32px; min-width: 36px; padding: 0; border: 0; color: var(--muted); font-size: 20px; font-weight: 400; }
.add:hover { color: var(--rim); }
@media (hover: none) { .add { min-height: 44px; min-width: 44px; } }
</style>
