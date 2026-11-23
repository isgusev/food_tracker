<script setup lang="ts">
// День плана: приёмы пищи с порцией выбранного едока и его КБЖУ против цели.
import { computed, onMounted, ref, watch } from "vue";
import { api, ok } from "../../api/client";
import { ensureCatalog } from "../../catalog";
import AddItemModal from "../../components/plan/AddItemModal.vue";
import MacroMeters from "../../components/plan/MacroMeters.vue";
import MemberSwitch from "../../components/plan/MemberSwitch.vue";
import PlanItemModal from "../../components/plan/PlanItemModal.vue";
import { itemBadge, memberMacros, portionOf, stateClass, type Item } from "../../plan";
import { hasTargets, session, targetsForMeters, toastError, viewMember } from "../../session";
import { MEALS, addDays, capitalize, dayMonth, fmt, grams, range, startOfWeek, today, weekday } from "../../util";

const props = defineProps<{ date: string }>();
const items = ref<Item[]>([]);
const adding = ref<string | null>(null);
const opened = ref<Item | null>(null);
const todayIso = today();

async function load() {
  try {
    await ensureCatalog();
    items.value = await ok(api.GET("/api/v1/plan", { params: { query: { start_date: props.date, end_date: props.date } } }));
  } catch (e) { toastError(e); }
}
watch(() => props.date, load);
onMounted(load);

const memberId = computed(() => session.viewMemberId);
const targets = computed(() => targetsForMeters(viewMember.value));
const byMeal = computed(() => Object.fromEntries(MEALS.map((m) => [m.key, items.value.filter((i) => i.meal_type === m.key)])));
const all = computed(() => memberMacros(items.value, memberId.value));
const eaten = computed(() => memberMacros(items.value, memberId.value, true));
const left = computed(() => ({ calories: targets.value.calories - all.value.calories, proteins: targets.value.proteins - all.value.proteins }));
const others = (it: Item) => it.portions.filter((p) => p.member_id !== memberId.value);
const weekDays = computed(() => range(startOfWeek(props.date), addDays(startOfWeek(props.date), 6)));
</script>

<template>
  <div class="day">
    <header class="head">
      <RouterLink :to="{ path: '/plan', query: { week: startOfWeek(date) } }" class="btn back">‹ Неделя</RouterLink>
      <div class="title">
        <h1 class="display">{{ capitalize(weekday(date)) }}, {{ dayMonth(date) }}</h1>
        <span v-if="date === todayIso" class="today-mark">сегодня</span>
      </div>
      <div class="nav">
        <RouterLink class="btn icon" :to="'/day/' + addDays(date, -1)" aria-label="Предыдущий день">‹</RouterLink>
        <RouterLink class="btn icon" :to="'/day/' + addDays(date, 1)" aria-label="Следующий день">›</RouterLink>
      </div>
    </header>
    <MemberSwitch />

    <div class="grid">
      <div class="meals">
        <section v-for="m in MEALS" :key="m.key" class="meal">
          <header class="meal-head">
            <h2>{{ m.label }}</h2>
            <button class="small" @click="adding = m.key">+ Добавить</button>
          </header>
          <p v-if="!byMeal[m.key].length" class="small muted empty">Пусто</p>
          <button v-for="it in byMeal[m.key]" :key="it.id" class="row" :class="[stateClass(it), { auto: it.origin === 'auto' }]" @click="opened = it">
            <span class="main">
              <span class="name">{{ it.name }}</span>
              <span class="badge" :class="itemBadge(it).cls">{{ itemBadge(it).text }}</span>
              <span class="small muted" v-if="portionOf(it, memberId)">
                {{ viewMember?.name }}: <b>{{ grams(portionOf(it, memberId)!.weight_g) }}</b> · {{ fmt(portionOf(it, memberId)!.calories) }} ккал
                <template v-if="portionOf(it, memberId)!.is_eaten"> · ✓ съел</template>
              </span>
              <span v-else class="small muted">{{ viewMember?.name }} это не ест</span>
              <span v-if="others(it).length" class="tiny muted">Ещё: <template v-for="(p, i) in others(it)" :key="p.id">{{ i ? ", " : "" }}{{ p.member_name || "гость" }} {{ fmt(p.weight_g) }} г{{ p.is_eaten ? " ✓" : "" }}</template></span>
            </span>
          </button>
        </section>
      </div>

      <aside class="pot side">
        <h2>КБЖУ: {{ viewMember?.name }}</h2>
        <p class="small muted">План и съеденное против цели<template v-if="!hasTargets(viewMember)"> (цели не заданы — показан ориентир)</template></p>
        <MacroMeters :value="all" :target="targets" />
        <p v-if="eaten.calories" class="small">Уже съедено {{ fmt(eaten.calories) }} ккал · Б {{ fmt(eaten.proteins) }} · Ж {{ fmt(eaten.fats) }} · У {{ fmt(eaten.carbs) }}</p>
        <p class="small">
          <template v-if="left.calories >= 0">Можно добавить ещё <b>{{ fmt(left.calories) }}</b> ккал</template>
          <span v-else class="over">Перебор на <b>{{ fmt(-left.calories) }}</b> ккал</span>
          <template v-if="left.proteins > 0">, не хватает <b>{{ fmt(left.proteins) }}</b> г белка</template>.
        </p>
        <RouterLink to="/family" class="small">Цели членов семьи</RouterLink>
      </aside>
    </div>

    <AddItemModal v-if="adding" :date="date" :meal="adding" :days="weekDays" @close="adding = null" @saved="adding = null; load()" />
    <PlanItemModal v-if="opened" :item="opened" @close="opened = null; load()" />
  </div>
</template>

<style scoped>
.day { display: flex; flex-direction: column; gap: 14px; }
.head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.title { flex: 1; display: flex; align-items: center; gap: 10px; min-width: 200px; }
h1 { font-size: 26px; color: var(--rim); }
.today-mark { font-size: 12px; font-weight: 700; color: var(--beak); background: var(--beak-soft); padding: 2px 10px; border-radius: 999px; }
.back { font-size: 14px; }
.nav { display: flex; gap: 6px; }
.icon { min-width: 44px; padding: 0; }
.grid { display: grid; grid-template-columns: 1fr 320px; gap: 16px; align-items: start; }
@media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
.meals { display: flex; flex-direction: column; gap: 12px; }
.meal { background: var(--enamel); border: 1.5px solid var(--line); border-radius: var(--r-pot); padding: 12px 14px; }
.meal-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
h2 { font-size: 18px; }
.meal-head button { min-height: 40px; font-size: 14px; }
.empty { margin: 0; }
.row {
  width: 100%; min-height: 0; display: flex; align-items: flex-start; gap: 10px; text-align: left; font-weight: 400;
  color: var(--ink); border: 0; border-radius: var(--r-in); padding: 10px 10px 10px 14px; margin-top: 6px;
  background: var(--enamel-2); position: relative;
}
.row::before { content: ""; position: absolute; left: 0; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0; background: var(--line); }
.st-to_cook::before { background: var(--cook); }
.st-in_fridge::before { background: var(--rim); }
.st-product::before { background: var(--sky); }
.row.auto { background: repeating-linear-gradient(-45deg, transparent 0 6px, var(--graphite-soft) 6px 7px), var(--enamel); border: 1px dashed var(--graphite); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.name { font-weight: 600; }
.badge { align-self: flex-start; font-size: 12px; padding: 2px 10px; border-radius: 999px; background: var(--enamel); color: var(--muted); }
.badge.ok { background: var(--rim-soft); color: var(--rim); }
.badge.warn { background: var(--beak-soft); color: var(--cook); }
.badge.info { color: var(--sky); }
.side { padding: 16px; display: flex; flex-direction: column; gap: 10px; position: sticky; top: 16px; }
.side p { margin: 0; }
.over { color: var(--tomato); }
</style>
