// План семьи на неделю и детальный день (личные КБЖУ выбранного члена семьи).
import { ref, computed, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Macros, MacroMeters } from "../components.js";
import {
  state, ensureCatalog, toast, toastError, activeMembers, members, viewMember, setViewMember,
  targetsForMeters, hasTargets,
} from "../store.js";
import {
  MEALS, MEAL_ORDER, addDays, fmt, fmtDayMonth, fmtDayMonthLong, fmtWeekday, fmtWeekdayLong,
  grams, local, n, range, startOfWeek, today,
} from "../util.js";
import {
  AddItemModal, ItemModal, allEaten, itemBadge, itemIcon, memberMacros, portionOf, portionsSummary,
} from "./plan-modals.js";

function byMeal(items) {
  const out = Object.fromEntries(MEALS.map((m) => [m.key, []]));
  for (const it of items) (out[it.meal_type] ||= []).push(it);
  return out;
}

// Переключатель «чьи КБЖУ показываем»
const MemberSwitch = {
  setup() {
    return { state, members: activeMembers, setViewMember };
  },
  template: `
    <div class="segmented" style="flex-wrap: wrap" v-if="members.length > 1" title="Чьи КБЖУ показывать">
      <button v-for="m in members" :key="m.id" :class="{ on: state.viewMemberId === m.id }" @click="setViewMember(m.id)">{{ m.name }}</button>
    </div>`,
};

export const PlannerView = {
  components: { AddItemModal, ItemModal, Macros, MemberSwitch },
  props: { query: Object },
  setup(props) {
    const weekStart = ref(startOfWeek(props.query?.week || local.get("ft.week", today())));
    const items = ref([]);
    const loading = ref(false);
    const adding = ref(null);
    const opened = ref(null);
    const days = computed(() => range(weekStart.value, addDays(weekStart.value, 6)));
    const weekEnd = computed(() => addDays(weekStart.value, 6));
    const me = computed(() => viewMember.value);
    const targets = computed(() => targetsForMeters(me.value));

    async function load() {
      loading.value = true;
      try {
        await ensureCatalog();
        items.value = await api.get("/plan", { start_date: weekStart.value, end_date: weekEnd.value });
      } catch (e) { toastError(e); } finally { loading.value = false; }
    }
    watch(weekStart, (w) => { local.set("ft.week", w); load(); });
    onMounted(load);

    const byDay = computed(() => {
      const map = Object.fromEntries(days.value.map((d) => [d, []]));
      for (const it of items.value) map[it.date_day]?.push(it);
      for (const d in map) map[d].sort((a, b) => MEAL_ORDER[a.meal_type] - MEAL_ORDER[b.meal_type] || a.id - b.id);
      return map;
    });
    const dayInfo = computed(() => Object.fromEntries(days.value.map((d) => {
      const list = byDay.value[d];
      const all = memberMacros(list, state.viewMemberId);
      const eaten = memberMacros(list, state.viewMemberId, true);
      return [d, { meals: byMeal(list), all, eaten, pct: Math.min(100, (all.calories / (targets.value.calories || 1)) * 100) }];
    })));
    const weekStats = computed(() => {
      const open = items.value.filter((it) => !allEaten(it));
      return {
        total: items.value.length,
        toCook: new Set(open.filter((it) => it.state === "to_cook").map((it) => it.recipe_id)).size,
        products: open.filter((it) => it.kind === "product").length,
        avgKcal: memberMacros(items.value, state.viewMemberId).calories / 7,
      };
    });

    async function copyPrevWeek() {
      const src = await api.get("/plan", { start_date: addDays(weekStart.value, -7), end_date: addDays(weekStart.value, -1) });
      if (!src.length) { toast("На прошлой неделе нет блюд"); return; }
      const msg = `Скопировать ${src.length} блюд с прошлой недели (с теми же порциями)?` +
        (items.value.length ? `\nНа этой неделе уже есть ${items.value.length} блюд — они останутся.` : "");
      if (!confirm(msg)) return;
      try {
        for (const it of src) {
          if (!it.recipe_id && !it.variant_id) continue; // рецепт удалён — копировать нечего
          await api.post("/plan", {
            date_day: addDays(it.date_day, 7),
            meal_type: it.meal_type,
            ...(it.kind === "product" ? { variant_id: it.variant_id } : { recipe_id: it.recipe_id }),
            portions: it.portions.map((p) => ({ member_id: p.member_id, weight_g: n(p.weight_g) })),
          });
        }
        toast("План скопирован");
      } catch (e) { toastError(e); }
      load();
    }

    const shopHref = computed(() => {
      const start = weekStart.value < today() && weekEnd.value >= today() ? today() : weekStart.value;
      return `#/shopping?start=${start}&end=${weekEnd.value}`;
    });
    function onChanged() { load(); }

    return {
      weekStart, weekEnd, days, dayInfo, weekStats, loading, adding, opened, me, targets, MEALS, state,
      copyPrevWeek, shopHref, onChanged, itemIcon, itemBadge, portionOf, portionsSummary, allEaten,
      prev: () => (weekStart.value = addDays(weekStart.value, -7)),
      next: () => (weekStart.value = addDays(weekStart.value, 7)),
      thisWeek: () => (weekStart.value = startOfWeek(today())),
      today: today(), fmt, grams, fmtDayMonth, fmtWeekday, n, hasTargets,
    };
  },
  template: `
    <div>
      <div class="page-head">
        <div class="row">
          <h1>План семьи</h1>
          <div class="row tight">
            <button class="icon" @click="prev" aria-label="Предыдущая неделя">‹</button>
            <span class="num" style="min-width: 150px; text-align: center">{{ fmtDayMonth(weekStart) }} — {{ fmtDayMonth(weekEnd) }}</span>
            <button class="icon" @click="next" aria-label="Следующая неделя">›</button>
            <button class="sm ghost" @click="thisWeek" v-if="weekStart > today || weekEnd < today">Текущая</button>
          </div>
        </div>
        <div class="row">
          <button @click="copyPrevWeek" title="Повторить план прошлой недели">⧉ Копировать прошлую неделю</button>
          <a class="btn" :href="shopHref" style="background: var(--accent); color: #fff; border-color: var(--accent)">🛒 Покупки на неделю</a>
        </div>
      </div>

      <div class="row" style="margin-bottom: 12px; gap: 16px">
        <MemberSwitch />
        <span class="small muted">Блюд: <b class="num">{{ weekStats.total }}</b></span>
        <span class="small muted">Приготовить: <b class="num">{{ weekStats.toCook }}</b></span>
        <span class="small muted">Купить готовым: <b class="num">{{ weekStats.products }}</b></span>
        <span class="small muted" v-if="me">{{ me.name }} в среднем: <b class="num">{{ fmt(weekStats.avgKcal) }}</b> ккал/день<template v-if="hasTargets(me)"> (цель {{ fmt(targets.calories) }})</template></span>
        <span v-if="loading" class="small muted">Загрузка…</span>
      </div>

      <div class="week">
        <div v-for="d in days" :key="d" class="day" :class="{ today: d === today }">
          <a class="day-head" :href="'#/day/' + d" style="text-decoration: none; color: inherit; display: block">
            <div class="row between">
              <span class="day-title">{{ fmtWeekday(d) }}, {{ fmtDayMonth(d) }}</span>
              <span class="small num muted" :title="me ? 'КБЖУ: ' + me.name : ''">{{ fmt(dayInfo[d].all.calories) }} ккал</span>
            </div>
            <div class="meter k" style="margin-top: 6px"><i :class="{ over: dayInfo[d].all.calories > targets.calories * 1.1 }" :style="{ width: dayInfo[d].pct + '%' }"></i></div>
            <div class="tiny muted num" style="margin-top: 4px">
              Б {{ fmt(dayInfo[d].all.proteins) }} · Ж {{ fmt(dayInfo[d].all.fats) }} · У {{ fmt(dayInfo[d].all.carbs) }}
              <span v-if="dayInfo[d].eaten.calories"> · съедено {{ fmt(dayInfo[d].eaten.calories) }}</span>
            </div>
          </a>
          <div v-for="m in MEALS" :key="m.key" class="meal">
            <div class="meal-head">
              <span>{{ m.label }}</span>
              <button class="add-btn" @click="adding = { date: d, meal: m.key }" :aria-label="'Добавить: ' + m.label">+</button>
            </div>
            <div v-for="it in dayInfo[d].meals[m.key]" :key="it.id" class="entry" :class="{ fact: allEaten(it) }" @click="opened = it">
              <span class="ico">{{ itemIcon(it) }}</span>
              <div class="grow">
                <div class="name">{{ it.name }}</div>
                <div class="meta">
                  <template v-if="portionOf(it, state.viewMemberId)">
                    {{ grams(portionOf(it, state.viewMemberId).weight_g) }} · {{ fmt(portionOf(it, state.viewMemberId).calories) }} ккал<span v-if="portionOf(it, state.viewMemberId).is_eaten"> ✓</span>
                  </template>
                  <template v-else>без {{ me?.name || 'вас' }}</template>
                  <span v-if="it.portions.length > 1"> · ещё {{ it.portions.length - (portionOf(it, state.viewMemberId) ? 1 : 0) }}</span>
                </div>
                <div v-if="!allEaten(it) && itemBadge(it).cls === 'warn'" class="tiny" style="color: var(--warn)">{{ itemBadge(it).text }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <AddItemModal v-if="adding" :date="adding.date" :meal="adding.meal" :days="days" @close="adding = null" @saved="adding = null; onChanged()" />
      <ItemModal v-if="opened" :item="opened" @close="opened = null; onChanged()" @changed="onChanged" />
    </div>`,
};

export const DayView = {
  components: { AddItemModal, ItemModal, Macros, MacroMeters, MemberSwitch },
  props: { date: String },
  setup(props) {
    const items = ref([]);
    const adding = ref(null);
    const opened = ref(null);
    async function load() {
      try {
        await ensureCatalog();
        items.value = await api.get("/plan", { start_date: props.date, end_date: props.date });
      } catch (e) { toastError(e); }
    }
    watch(() => props.date, load);
    onMounted(load);

    const me = computed(() => viewMember.value);
    const targets = computed(() => targetsForMeters(me.value));
    const meals = computed(() => byMeal(items.value));
    const all = computed(() => memberMacros(items.value, state.viewMemberId));
    const eaten = computed(() => memberMacros(items.value, state.viewMemberId, true));
    const left = computed(() => ({
      calories: targets.value.calories - all.value.calories,
      proteins: targets.value.proteins - all.value.proteins,
    }));
    const others = (it) => it.portions.filter((p) => p.member_id !== state.viewMemberId);
    return {
      items, meals, all, eaten, left, me, targets, adding, opened, MEALS, state, load,
      itemIcon, itemBadge, portionOf, others, allEaten, hasTargets,
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
      <div style="margin-bottom: 12px"><MemberSwitch /></div>

      <div class="day-detail-grid">
        <div class="stack">
          <div v-for="m in MEALS" :key="m.key" class="card flush">
            <div class="row between" style="padding: 12px 14px; border-bottom: 1px solid var(--border)">
              <h2>{{ m.label }}</h2>
              <button class="sm" @click="adding = { meal: m.key }">+ Добавить</button>
            </div>
            <div v-if="!meals[m.key].length" class="muted small" style="padding: 12px 14px">Пусто</div>
            <div v-for="it in meals[m.key]" :key="it.id" class="list-item clickable" @click="opened = it">
              <span style="width: 20px; text-align: center">{{ itemIcon(it) }}</span>
              <div class="grow stack tight">
                <div class="row between">
                  <b>{{ it.name }}</b>
                  <span class="badge" :class="itemBadge(it).cls">{{ itemBadge(it).text }}</span>
                </div>
                <div class="row between" v-if="portionOf(it, state.viewMemberId)">
                  <span class="small">{{ me?.name }}: <b class="num">{{ grams(portionOf(it, state.viewMemberId).weight_g) }}</b>
                    <span v-if="portionOf(it, state.viewMemberId).is_eaten" class="badge ok" style="margin-left: 4px">✓ съел</span></span>
                  <Macros :m="portionOf(it, state.viewMemberId)" :digits="1" />
                </div>
                <div v-else class="small muted">{{ me?.name }} это не ест</div>
                <div class="tiny muted" v-if="others(it).length">
                  Ещё: <span v-for="(p, i) in others(it)" :key="p.id">{{ i ? ', ' : '' }}{{ p.member_name || 'гость' }} {{ fmt(p.weight_g) }} г{{ p.is_eaten ? ' ✓' : '' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="stack" style="position: sticky; top: 16px">
          <div class="card stack">
            <h2>КБЖУ: {{ me?.name }}</h2>
            <div class="small muted">План + съеденное против цели<template v-if="!hasTargets(me)"> (цели не заданы — показан ориентир)</template></div>
            <MacroMeters :value="all" :target="targets" />
            <div class="small" v-if="eaten.calories"><span class="muted">Уже съедено: </span><Macros :m="eaten" /></div>
            <div class="small">
              <template v-if="left.calories >= 0">Можно добавить ещё <b class="num">{{ fmt(left.calories) }}</b> ккал</template>
              <template v-else><span style="color: var(--danger)">Перебор на <b class="num">{{ fmt(-left.calories) }}</b> ккал</span></template>
              <template v-if="left.proteins > 0">, не хватает <b class="num">{{ fmt(left.proteins) }}</b> г белка</template>.
            </div>
            <a href="#/family" class="small">Цели членов семьи</a>
          </div>
        </div>
      </div>

      <AddItemModal v-if="adding" :date="date" :meal="adding.meal" :days="weekDays" @close="adding = null" @saved="adding = null; load()" />
      <ItemModal v-if="opened" :item="opened" @close="opened = null; load()" @changed="load" />
    </div>`,
};
