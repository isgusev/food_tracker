// Недельный планировщик и детальный день (личные КБЖУ против целей).
import { ref, computed, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Macros, MacroMeters } from "../components.js";
import { ensureCatalog, getTargets, toast, toastError } from "../store.js";
import {
  MEALS, MEAL_ORDER, STATUS, addDays, fmt, fmtDayMonth, fmtDayMonthLong, fmtWeekday, fmtWeekdayLong,
  grams, local, n, range, startOfWeek, sumMacros, today,
} from "../util.js";
import { AddEntryModal, EntryModal, entryName, sourceBadge } from "./entry-modals.js";

function byMeal(entries) {
  const out = Object.fromEntries(MEALS.map((m) => [m.key, []]));
  for (const e of entries) (out[e.meal_type] ||= []).push(e);
  return out;
}

export const PlannerView = {
  components: { AddEntryModal, EntryModal, Macros },
  props: { query: Object },
  setup(props) {
    const weekStart = ref(startOfWeek(props.query?.week || local.get("ft.week", today())));
    const entries = ref([]);
    const loading = ref(false);
    const adding = ref(null);
    const editing = ref(null);
    const targets = getTargets();
    const days = computed(() => range(weekStart.value, addDays(weekStart.value, 6)));
    const weekEnd = computed(() => addDays(weekStart.value, 6));

    async function load() {
      loading.value = true;
      try {
        await ensureCatalog();
        entries.value = await api.get("/diary/range", { start_date: weekStart.value, end_date: weekEnd.value });
      } catch (e) { toastError(e); } finally { loading.value = false; }
    }
    watch(weekStart, (w) => { local.set("ft.week", w); load(); });
    onMounted(load);

    const byDay = computed(() => {
      const map = Object.fromEntries(days.value.map((d) => [d, []]));
      for (const e of entries.value) map[e.date_day]?.push(e);
      for (const d in map) map[d].sort((a, b) => MEAL_ORDER[a.meal_type] - MEAL_ORDER[b.meal_type] || a.id - b.id);
      return map;
    });
    const dayInfo = computed(() => Object.fromEntries(days.value.map((d) => {
      const list = byDay.value[d];
      const all = sumMacros(list);
      const fact = sumMacros(list.filter((e) => e.status === "fact"));
      return [d, { meals: byMeal(list), all, fact, pct: Math.min(100, (all.calories / (targets.calories || 1)) * 100) }];
    })));
    const weekStats = computed(() => {
      const plans = entries.value.filter((e) => e.status !== "fact");
      const toCook = plans.filter((e) => e.kind === "recipe" && e.status === "template_plan");
      return {
        total: entries.value.length,
        toCook: new Set(toCook.map((e) => e.recipe_id)).size,
        products: plans.filter((e) => e.kind === "product").length,
        avgKcal: sumMacros(entries.value).calories / 7,
      };
    });

    async function copyPrevWeek() {
      const src = await api.get("/diary/range", { start_date: addDays(weekStart.value, -7), end_date: addDays(weekStart.value, -1) });
      if (!src.length) { toast("На прошлой неделе нет записей"); return; }
      const msg = `Скопировать ${src.length} записей с прошлой недели как планы?` +
        (entries.value.length ? `\nНа этой неделе уже есть ${entries.value.length} записей — они останутся.` : "");
      if (!confirm(msg)) return;
      try {
        for (const e of src) {
          const body = {
            date_day: addDays(e.date_day, 7), meal_type: e.meal_type,
            weight_g: n(e.weight_g), servings_multiplier: e.servings_multiplier || 1,
          };
          if (e.kind === "product") body.variant_id = e.variant_id;
          else if (e.recipe_id) body.recipe_id = e.recipe_id;
          else continue; // рецепт удалён — копировать нечего
          await api.post("/diary/", body);
        }
        toast("План скопирован");
      } catch (e) { toastError(e); }
      load();
    }

    const shopHref = computed(() => {
      const start = weekStart.value < today() && weekEnd.value >= today() ? today() : weekStart.value;
      return `#/shopping?start=${start}&end=${weekEnd.value}`;
    });

    function onSaved() { adding.value = null; editing.value = null; load(); }

    return {
      weekStart, weekEnd, days, byDay, dayInfo, weekStats, loading, adding, editing, targets, MEALS, STATUS,
      load, copyPrevWeek, shopHref, onSaved, entryName, sourceBadge,
      prev: () => (weekStart.value = addDays(weekStart.value, -7)),
      next: () => (weekStart.value = addDays(weekStart.value, 7)),
      thisWeek: () => (weekStart.value = startOfWeek(today())),
      today: today(), fmt, grams, fmtDayMonth, fmtWeekday, n,
    };
  },
  template: `
    <div>
      <div class="page-head">
        <div class="row">
          <h1>План питания</h1>
          <div class="row tight">
            <button class="icon" @click="prev" aria-label="Предыдущая неделя">‹</button>
            <span class="num" style="min-width: 150px; text-align: center">{{ fmtDayMonth(weekStart) }} — {{ fmtDayMonth(weekEnd) }}</span>
            <button class="icon" @click="next" aria-label="Следующая неделя">›</button>
            <button class="sm ghost" @click="thisWeek" v-if="weekStart > today || weekEnd < today">Текущая</button>
          </div>
        </div>
        <div class="row">
          <button @click="copyPrevWeek" title="Повторить план прошлой недели">⧉ Копировать прошлую неделю</button>
          <a class="btn primary" :href="shopHref" style="background: var(--accent); color: #fff; border-color: var(--accent)">🛒 Покупки на неделю</a>
        </div>
      </div>

      <div class="row small muted" style="margin-bottom: 12px; gap: 16px">
        <span>Записей: <b class="num">{{ weekStats.total }}</b></span>
        <span>Блюд приготовить: <b class="num">{{ weekStats.toCook }}</b></span>
        <span>Готовых продуктов: <b class="num">{{ weekStats.products }}</b></span>
        <span>В среднем: <b class="num">{{ fmt(weekStats.avgKcal) }}</b> ккал/день (цель {{ fmt(targets.calories) }})</span>
        <span v-if="loading">Загрузка…</span>
      </div>

      <div class="week">
        <div v-for="d in days" :key="d" class="day" :class="{ today: d === today }">
          <a class="day-head" :href="'#/day/' + d" style="text-decoration: none; color: inherit; display: block">
            <div class="row between">
              <span class="day-title">{{ fmtWeekday(d) }}, {{ fmtDayMonth(d) }}</span>
              <span class="small num muted">{{ fmt(dayInfo[d].all.calories) }} ккал</span>
            </div>
            <div class="meter k" style="margin-top: 6px"><i :class="{ over: dayInfo[d].all.calories > targets.calories * 1.1 }" :style="{ width: dayInfo[d].pct + '%' }"></i></div>
            <div class="tiny muted num" style="margin-top: 4px">
              Б {{ fmt(dayInfo[d].all.proteins) }} · Ж {{ fmt(dayInfo[d].all.fats) }} · У {{ fmt(dayInfo[d].all.carbs) }}
              <span v-if="dayInfo[d].fact.calories"> · съедено {{ fmt(dayInfo[d].fact.calories) }}</span>
            </div>
          </a>
          <div v-for="m in MEALS" :key="m.key" class="meal">
            <div class="meal-head">
              <span>{{ m.label }}</span>
              <button class="add-btn" @click="adding = { date: d, meal: m.key }" :aria-label="'Добавить: ' + m.label">+</button>
            </div>
            <div v-for="e in dayInfo[d].meals[m.key]" :key="e.id" class="entry" :class="{ fact: e.status === 'fact' }" @click="editing = e">
              <span class="ico" :title="STATUS[e.status]?.label">{{ e.kind === 'product' ? '🛍' : STATUS[e.status]?.icon }}</span>
              <div class="grow">
                <div class="name">{{ entryName(e) }}</div>
                <div class="meta">{{ grams(e.weight_g) }} · {{ fmt(e.calories) }} ккал<span v-if="(e.servings_multiplier || 1) > 1"> · ×{{ e.servings_multiplier }} чел</span></div>
                <div v-if="e.status !== 'fact' && e.kind === 'recipe' && sourceBadge(e).cls === 'warn'" class="tiny" style="color: var(--warn)">{{ sourceBadge(e).text }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <AddEntryModal v-if="adding" :date="adding.date" :meal="adding.meal" :days="days" @close="adding = null" @saved="onSaved" />
      <EntryModal v-if="editing" :entry="editing" @close="editing = null" @saved="onSaved" />
    </div>`,
};

export const DayView = {
  components: { AddEntryModal, EntryModal, Macros, MacroMeters },
  props: { date: String },
  setup(props) {
    const entries = ref([]);
    const adding = ref(null);
    const editing = ref(null);
    const targets = getTargets();
    async function load() {
      try {
        await ensureCatalog();
        entries.value = await api.get(`/diary/day/${props.date}`);
      } catch (e) { toastError(e); }
    }
    watch(() => props.date, load);
    onMounted(load);

    const sorted = computed(() => [...entries.value].sort((a, b) => MEAL_ORDER[a.meal_type] - MEAL_ORDER[b.meal_type] || a.id - b.id));
    const meals = computed(() => byMeal(sorted.value));
    const fact = computed(() => sumMacros(entries.value.filter((e) => e.status === "fact")));
    const all = computed(() => sumMacros(entries.value));
    const left = computed(() => ({
      calories: targets.calories - all.value.calories,
      proteins: targets.proteins - all.value.proteins,
    }));
    function onSaved() { adding.value = null; editing.value = null; load(); }
    return {
      entries, meals, fact, all, left, targets, adding, editing, MEALS, STATUS, onSaved, entryName, sourceBadge,
      prevHref: computed(() => `#/day/${addDays(props.date, -1)}`),
      nextHref: computed(() => `#/day/${addDays(props.date, 1)}`),
      weekHref: computed(() => `#/plan?week=${startOfWeek(props.date)}`),
      weekDays: computed(() => range(startOfWeek(props.date), addDays(startOfWeek(props.date), 6))),
      fmt, grams, fmtWeekdayLong, fmtDayMonthLong, today: today(),
    };
  },
  template: `
    <div>
      <div class="page-head">
        <div class="row">
          <a :href="weekHref" class="btn ghost sm">‹ Неделя</a>
          <h1>{{ fmtWeekdayLong(date) }}, {{ fmtDayMonthLong(date) }}</h1>
          <span v-if="date === today" class="badge ok">сегодня</span>
        </div>
        <div class="row tight">
          <a class="btn icon" :href="prevHref" aria-label="Предыдущий день">‹</a>
          <a class="btn icon" :href="nextHref" aria-label="Следующий день">›</a>
        </div>
      </div>

      <div class="day-detail-grid">
        <div class="stack">
          <div v-for="m in MEALS" :key="m.key" class="card flush">
            <div class="row between" style="padding: 12px 14px; border-bottom: 1px solid var(--border)">
              <h2>{{ m.label }}</h2>
              <div class="row">
                <span class="small muted" v-if="meals[m.key].length"><Macros :m="{ calories: meals[m.key].reduce((s, e) => s + Number(e.calories), 0) }" kcalOnly /></span>
                <button class="sm" @click="adding = { meal: m.key }">+ Добавить</button>
              </div>
            </div>
            <div v-if="!meals[m.key].length" class="muted small" style="padding: 12px 14px">Пусто</div>
            <div v-for="e in meals[m.key]" :key="e.id" class="list-item clickable" @click="editing = e">
              <span style="width: 20px; text-align: center">{{ e.kind === 'product' ? '🛍' : STATUS[e.status]?.icon }}</span>
              <div class="grow stack tight">
                <div class="row between"><b>{{ entryName(e) }}</b><span class="num nowrap">{{ grams(e.weight_g) }}</span></div>
                <div class="row between">
                  <Macros :m="e" :digits="1" />
                  <span class="row tight">
                    <span class="badge" :class="STATUS[e.status]?.cls">{{ STATUS[e.status]?.label }}</span>
                    <span class="badge" :class="sourceBadge(e).cls">{{ sourceBadge(e).text }}</span>
                    <span v-if="(e.servings_multiplier || 1) > 1" class="badge">×{{ e.servings_multiplier }} чел</span>
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="stack" style="position: sticky; top: 16px">
          <div class="card stack">
            <h2>Мои КБЖУ за день</h2>
            <div class="small muted">План + съеденное против цели</div>
            <MacroMeters :value="all" :target="targets" />
            <div class="small" v-if="fact.calories"><span class="muted">Уже съедено: </span><Macros :m="fact" /></div>
            <div class="small">
              <template v-if="left.calories >= 0">Можно добавить ещё <b class="num">{{ fmt(left.calories) }}</b> ккал</template>
              <template v-else><span style="color: var(--danger)">Перебор на <b class="num">{{ fmt(-left.calories) }}</b> ккал</span></template>
              <template v-if="left.proteins > 0">, не хватает <b class="num">{{ fmt(left.proteins) }}</b> г белка</template>.
            </div>
            <a href="#/profile" class="small">Изменить цели</a>
          </div>
        </div>
      </div>

      <AddEntryModal v-if="adding" :date="date" :meal="adding.meal" :days="weekDays" @close="adding = null" @saved="onSaved" />
      <EntryModal v-if="editing" :entry="editing" @close="editing = null" @saved="onSaved" />
    </div>`,
};
