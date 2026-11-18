import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Macros, MacroMeters, Modal } from "../../components.js";
import {
  state, ensureCatalog, toast, toastError, activeMembers, members, viewMember, setViewMember,
  targetsForMeters, hasTargets,
} from "../../store.js";
import {
  MEALS, MEAL_ORDER, addDays, fmt, fmtDayMonth, fmtDayMonthLong, fmtWeekday, fmtWeekdayLong,
  grams, local, n, range, startOfWeek, today,
} from "../../util.js";

import {
  AddItemModal, ItemModal, allEaten, itemBadge, itemIcon, memberMacros, portionOf, portionsSummary,
} from "../plan-modals.js";
import { fmtMonth, byMeal } from "./shared.js";
import { MemberSwitch } from "./MemberSwitch.js";
import { TemplatesModal } from "./TemplatesModal.js";

export const PlannerView = {
  components: { AddItemModal, ItemModal, Macros, MemberSwitch, TemplatesModal },
  props: { query: Object },
  setup(props) {
    const weekStart = ref(startOfWeek(props.query?.week || local.get("ft.week", today())));
    const items = ref([]);
    const loading = ref(false);
    const adding = ref(null);
    const opened = ref(null);
    const templates = ref(false);
    // Перетаскивание блюда мышью на другой день / приём пищи
    const dragId = ref(null);
    const dropTarget = ref("");
    async function dropTo(d, meal) {
      const id = dragId.value;
      dragId.value = null;
      dropTarget.value = "";
      const it = items.value.find((x) => x.id === id);
      if (!it || (it.date_day === d && it.meal_type === meal)) return;
      try {
        await api.patch(`/plan/${id}`, { date_day: d, meal_type: meal });
        await load();
      } catch (e) { toastError(e); }
    }
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

    // Автоплан: «✨ Предложить» заполняет пустые ячейки (прежние предложения без 📌 — заменяет)
    const suggesting = ref("");   // "" | "week" | дата дня | "fridge"
    const firstOpen = computed(() => (weekStart.value < today() ? today() : weekStart.value));
    async function suggest(start, end, key, extra = {}) {
      suggesting.value = key;
      try {
        const r = await api.post("/plan/autofill", { start, end, ...extra });
        const k = r.items.length;
        toast(k
          ? `Предложено блюд: ${k}${r.replaced ? ` (прежних предложений заменено: ${r.replaced})` : ""}. Правьте или принимайте`
          : "Нечего предложить: ячейки заняты или нет рецептов в ротации");
        await load();
      } catch (e) { toastError(e); } finally { suggesting.value = ""; }
    }
    const suggestWeek = () => suggest(firstOpen.value, weekEnd.value, "week");
    const suggestDay = (d) => suggest(d, d, d);
    const fillFromFridge = () => suggest(firstOpen.value, weekEnd.value, "fridge", { cook: false });

    const drafts = computed(() => items.value.filter((it) => it.origin === "auto"));
    const loose = computed(() => drafts.value.filter((it) => !it.pinned && !it.cooking_log_id && !it.portions.some((p) => p.is_eaten)));
    const { run: act } = useAction({ done: () => load() });
    const acceptAll = () => act(() => api.post("/plan/accept", { start: weekStart.value, end: weekEnd.value }), "Предложения приняты — теперь это обычный план");
    async function clearDrafts() {
      if (!confirm(`Убрать предложения без 📌 (${loose.value.length})?`)) return;
      await act(async () => { for (const it of loose.value) await api.del(`/plan/${it.id}`); }, "Предложения убраны");
    }
    const accept = (it) => act(() => api.post(`/plan/${it.id}/accept`));
    const pin = (it) => act(() => api.patch(`/plan/${it.id}`, { pinned: !it.pinned }), it.pinned ? "Откреплено" : "Закреплено — перегенерация не тронет");
    const other = (it) => act(() => api.post(`/plan/${it.id}/alternative`));
    const drop = (it) => act(() => api.del(`/plan/${it.id}`));
    const canSwap = (it) => it.kind === "recipe" && !it.cooking_log_id && !it.portions.some((p) => p.is_eaten);

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
            ...(it.kind === "product" ? { variant_id: it.variant_id, exact: !!it.exact } : { recipe_id: it.recipe_id }),
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
      templates, dragId, dropTarget, dropTo, load,
      copyPrevWeek, fillFromFridge, shopHref, suggesting, suggestWeek, suggestDay, drafts, loose, acceptAll, clearDrafts,
      accept, pin, other, drop, canSwap, dayNum: (d) => Number(d.slice(8, 10)), fmtMonth, onChanged, itemIcon, itemBadge, portionOf, portionsSummary, allEaten,
      prev: () => (weekStart.value = addDays(weekStart.value, -7)),
      next: () => (weekStart.value = addDays(weekStart.value, 7)),
      thisWeek: () => (weekStart.value = startOfWeek(today())),
      today: today(), fmt, grams, fmtDayMonth, fmtWeekday, n, hasTargets,
    };
  },
  template: `
    <div class="planner">
      <div class="page-head">
        <div class="row">
          <h1>План семьи</h1>
          <div class="row tight">
            <button class="icon" @click="prev" aria-label="Предыдущая неделя">‹</button>
            <span class="num week-range">{{ fmtDayMonth(weekStart) }} — {{ fmtDayMonth(weekEnd) }}</span>
            <button class="icon" @click="next" aria-label="Следующая неделя">›</button>
            <button class="sm ghost" @click="thisWeek" v-if="weekStart > today || weekEnd < today">Текущая</button>
          </div>
        </div>
        <div class="row">
          <button class="suggest-btn" :disabled="!!suggesting || weekEnd < today" @click="suggestWeek"
                  title="Заполнить пустые приёмы пищи: остатки, заготовки, затем готовки из рецептов в ротации. Ваш план не трогается">
            <span aria-hidden="true">✨</span>{{ suggesting === 'week' ? 'Подбираю…' : 'Предложить неделю' }}
          </button>
          <button :disabled="!!suggesting || weekEnd < today" @click="fillFromFridge" title="Только остатки из холодильника и заготовки — без новых готовок">🧊 Только остатки</button>
          <button @click="copyPrevWeek" title="Повторить план прошлой недели">⧉ Прошлая неделя</button>
          <button @click="templates = true">Шаблоны</button>
          <a class="btn shop-link" :href="shopHref">🛒 Покупки на неделю</a>
        </div>
      </div>

      <div v-if="drafts.length" class="draft-bar" role="status">
        <span class="draft-swatch" aria-hidden="true"></span>
        <div class="grow">
          <b>Черновик: {{ drafts.length }} {{ drafts.length === 1 ? 'предложение' : drafts.length < 5 ? 'предложения' : 'предложений' }}</b>
          <div class="tiny muted">Карандашом — то, что предложил планировщик. Правка, ✓ или «Принять всё» делают блюдо обычным; 📌 — оставить при новом подборе.</div>
        </div>
        <button class="sm ghost" v-if="loose.length" @click="clearDrafts">Убрать</button>
        <button class="sm primary" @click="acceptAll">✓ Принять всё</button>
      </div>

      <div class="row week-stats">
        <MemberSwitch />
        <span class="small muted">Блюд: <b class="num">{{ weekStats.total }}</b></span>
        <span class="small muted">Приготовить: <b class="num">{{ weekStats.toCook }}</b></span>
        <span class="small muted">Купить готовым: <b class="num">{{ weekStats.products }}</b></span>
        <span class="small muted" v-if="me">{{ me.name }} в среднем: <b class="num">{{ fmt(weekStats.avgKcal) }}</b> ккал/день<template v-if="hasTargets(me)"> (цель {{ fmt(targets.calories) }})</template></span>
        <span v-if="loading" class="small muted">Загрузка…</span>
      </div>

      <div class="week">
        <section v-for="d in days" :key="d" class="day" :class="{ today: d === today, past: d < today }">
          <header class="day-head">
            <a class="day-date" :href="'#/day/' + d" :aria-label="'Открыть день ' + fmtDayMonth(d)">
              <span class="day-num num">{{ dayNum(d) }}</span>
              <span class="day-word"><b>{{ fmtWeekday(d) }}</b><span>{{ d === today ? 'сегодня' : fmtMonth(d) }}</span></span>
            </a>
            <span class="day-kcal num" :title="me ? 'КБЖУ: ' + me.name : ''">{{ fmt(dayInfo[d].all.calories) }}<small> ккал</small></span>
            <button v-if="d >= today" class="day-suggest" :disabled="!!suggesting" @click="suggestDay(d)"
                    :aria-label="'Предложить на ' + fmtDayMonth(d)" title="Предложить на этот день">{{ suggesting === d ? '…' : '✨' }}</button>
          </header>
          <div class="day-meter">
            <div class="meter k"><i :class="{ over: dayInfo[d].all.calories > targets.calories * 1.1 }" :style="{ width: dayInfo[d].pct + '%' }"></i></div>
            <div class="tiny muted num">
              Б {{ fmt(dayInfo[d].all.proteins) }} · Ж {{ fmt(dayInfo[d].all.fats) }} · У {{ fmt(dayInfo[d].all.carbs) }}
              <span v-if="dayInfo[d].eaten.calories"> · съедено {{ fmt(dayInfo[d].eaten.calories) }}</span>
            </div>
          </div>
          <div v-for="m in MEALS" :key="m.key" class="meal" :class="{ 'drop-on': dropTarget === d + m.key, empty: !dayInfo[d].meals[m.key].length }"
               @dragover.prevent="dropTarget = d + m.key" @dragleave="dropTarget === d + m.key && (dropTarget = '')" @drop.prevent="dropTo(d, m.key)">
            <div class="meal-head">
              <span>{{ m.label }}</span>
              <button class="add-btn" @click="adding = { date: d, meal: m.key }" :aria-label="'Добавить: ' + m.label">+</button>
            </div>
            <article v-for="it in dayInfo[d].meals[m.key]" :key="it.id" class="entry"
                 :class="['st-' + (it.kind === 'product' ? 'product' : it.state), { fact: allEaten(it), dragging: dragId === it.id, auto: it.origin === 'auto', pinned: it.pinned }]"
                 draggable="true" @dragstart="dragId = it.id; $event.dataTransfer.effectAllowed = 'move'" @dragend="dragId = null; dropTarget = ''"
                 @click="opened = it" title="Открыть; перетащите на другой день или приём пищи">
              <div class="entry-main">
                <span class="ico">{{ itemIcon(it) }}</span>
                <div class="grow">
                  <div class="name">{{ it.name }}<span v-if="it.pinned" class="pin-mark" title="Закреплено">📌</span></div>
                  <div class="meta">
                    <template v-if="portionOf(it, state.viewMemberId)">
                      {{ grams(portionOf(it, state.viewMemberId).weight_g) }} · {{ fmt(portionOf(it, state.viewMemberId).calories) }} ккал<span v-if="portionOf(it, state.viewMemberId).is_eaten"> ✓</span>
                    </template>
                    <template v-else>без {{ me?.name || 'вас' }}</template>
                    <span v-if="it.portions.length > 1"> · ещё {{ it.portions.length - (portionOf(it, state.viewMemberId) ? 1 : 0) }}</span>
                  </div>
                  <div v-if="!allEaten(it) && itemBadge(it).cls === 'warn'" class="tiny warn-text">{{ itemBadge(it).text }}</div>
                  <div v-if="it.origin === 'auto' && it.auto_reason" class="reason">{{ it.auto_reason }}</div>
                </div>
              </div>
              <div v-if="it.origin === 'auto'" class="draft-actions" @click.stop>
                <button class="da" @click="accept(it)" title="Принять — станет обычным блюдом" aria-label="Принять">✓</button>
                <button class="da" :class="{ on: it.pinned }" @click="pin(it)" :title="it.pinned ? 'Открепить' : 'Закрепить: новый подбор не заменит'" :aria-label="it.pinned ? 'Открепить' : 'Закрепить'">📌</button>
                <button class="da" v-if="canSwap(it)" @click="other(it)" title="Другой вариант" aria-label="Другой вариант">🔄</button>
                <button class="da" @click="drop(it)" title="Убрать из плана" aria-label="Убрать">✕</button>
              </div>
            </article>
          </div>
        </section>
      </div>

      <AddItemModal v-if="adding" :date="adding.date" :meal="adding.meal" :days="days" @close="adding = null" @saved="adding = null; onChanged()" />
      <ItemModal v-if="opened" :item="opened" @close="opened = null; onChanged()" @changed="onChanged" />
      <TemplatesModal v-if="templates" :weekStart="weekStart" @close="templates = false" @applied="templates = false; load()" />
    </div>`,
};
