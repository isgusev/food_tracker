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
import { byMeal } from "./shared.js";
import { MemberSwitch } from "./MemberSwitch.js";

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
