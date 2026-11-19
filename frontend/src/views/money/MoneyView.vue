<script setup lang="ts">
// Деньги: траты за месяц против бюджета (с прогнозом по плану «карандашом»), во что ушли деньги, что выбросили.
import { computed, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import { api, ok, type Schemas } from "../../api/client";
import { toast, toastError } from "../../session";
import { capitalize, fmt, num, plural, today } from "../../util";

const MONTH = new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric" });
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const monthStart = (s: string) => s.slice(0, 8) + "01";
const parse = (s: string) => new Date(s + "T12:00:00");
const monthEnd = (s: string) => { const d = parse(s); return iso(new Date(d.getFullYear(), d.getMonth() + 1, 0)); };
const shiftMonth = (s: string, k: number) => { const d = parse(s); return iso(new Date(d.getFullYear(), d.getMonth() + k, 1)); };
const rub = (v: unknown) => `${fmt(v)} ₽`;

const month = ref(monthStart(today()));
const data = ref<Schemas["FinanceSummary"] | null>(null);
const loading = ref(false);
async function load() {
  loading.value = true;
  try {
    const m = month.value;
    const r = await ok(api.GET("/api/v1/finance/summary", { params: { query: { start_date: m, end_date: monthEnd(m) } } }));
    if (m === month.value) data.value = r;     // успели переключить месяц — старый ответ не показываем
  } catch (e) { toastError(e); } finally { loading.value = false; }
}
watch(month, load, { immediate: true });

const isCurrent = computed(() => month.value === monthStart(today()));
const title = computed(() => capitalize(MONTH.format(parse(month.value)).replace(/\s*г\.$/, "")));
const budget = computed(() => (data.value?.monthly_budget != null ? num(data.value.monthly_budget) : null));
const spent = computed(() => num(data.value?.spent));
const planned = computed(() => (isCurrent.value ? num(data.value?.planned_to_buy) : 0));
const projected = computed(() => spent.value + planned.value);
const scale = computed(() => Math.max(budget.value ?? 0, projected.value, 1));   // полоса — до бюджета или прогноза
const pct = (v: number) => Math.min(100, (v / scale.value) * 100);
const maxCat = computed(() => Math.max(1, ...(data.value?.by_category ?? []).map((c) => num(c.spent))));
const empty = computed(() => !!data.value && !spent.value && !num(data.value.eaten_value) && !data.value.unpriced_purchases);

// ---- бюджет
const editing = ref(false);
const budgetInput = ref<number | string>("");
const saving = ref(false);
function edit() { budgetInput.value = budget.value ?? ""; editing.value = true; }
async function saveBudget() {
  saving.value = true;
  try {
    await ok(api.PUT("/api/v1/finance/budget", { body: { monthly_budget: budgetInput.value === "" ? null : num(budgetInput.value) } }));
    editing.value = false;
    toast(budgetInput.value === "" ? "Бюджет снят" : "Бюджет сохранён");
    await load();
  } catch (e) { toastError(e); } finally { saving.value = false; }
}
const badBudget = computed(() => budgetInput.value !== "" && (num(budgetInput.value) < 0 || num(budgetInput.value) > 99999999));
</script>

<template>
  <div class="money">
    <div class="head">
      <h1>Деньги</h1>
      <div class="months">
        <button class="text nav" aria-label="Предыдущий месяц" @click="month = shiftMonth(month, -1)">‹</button>
        <b class="mt">{{ title }}</b>
        <button class="text nav" aria-label="Следующий месяц" :disabled="isCurrent" @click="month = shiftMonth(month, 1)">›</button>
      </div>
    </div>

    <p v-if="!data" class="muted">{{ loading ? "Загружаю…" : "" }}</p>
    <template v-else>
      <section class="pot budget" :class="{ dim: loading }">
        <div class="bh">
          <h2>Бюджет на продукты</h2>
          <button v-if="!editing" class="text small" @click="edit">{{ budget == null ? "Задать" : "Изменить" }}</button>
        </div>
        <form v-if="editing" class="inline" @submit.prevent="saveBudget">
          <input v-model="budgetInput" type="number" min="0" step="100" inputmode="numeric" placeholder="₽ в месяц" class="bi" aria-label="Бюджет, ₽ в месяц">
          <button class="fill small" :disabled="saving || badBudget">{{ saving ? "Сохраняю…" : "Сохранить" }}</button>
          <button type="button" class="text small" @click="editing = false">Отмена</button>
          <span class="small muted block">Пусто — без бюджета. Бюджет общий для всех месяцев; при тугом бюджете автоплан чаще берёт недорогие блюда.</span>
        </form>

        <template v-if="budget != null">
          <div class="sum">
            <span>Потрачено <b class="big">{{ rub(spent) }}</b> из {{ rub(budget) }}</span>
            <b :class="spent > budget ? 'over' : 'left'">{{ spent > budget ? "перерасход " + rub(spent - budget) : "осталось " + rub(budget - spent) }}</b>
          </div>
          <div class="bar" :title="'Потрачено ' + rub(spent)">
            <i class="spent" :class="{ over: spent > budget }" :style="{ width: pct(spent) + '%' }"></i>
            <i v-if="planned > 0" class="plan" :class="{ over: projected > budget }" :style="{ width: pct(projected) - pct(spent) + '%' }"></i>
            <span v-if="projected > budget" class="limit" :style="{ left: pct(budget) + '%' }" title="Бюджет"></span>
          </div>
          <p v-if="planned > 0" class="small muted">
            По плану ещё купить ≈ <b>{{ rub(planned) }}</b> → к концу месяца ≈
            <b :class="{ over: projected > budget }">{{ rub(projected) }}</b><template v-if="data.planned_unknown">
            (у {{ data.planned_unknown }} {{ plural(data.planned_unknown, "позиции", "позиций", "позиций") }} цена ещё неизвестна)</template>
          </p>
        </template>
        <p v-else-if="!editing" class="small muted">Задайте месячный бюджет — будет видно, сколько осталось и хватит ли до конца месяца.</p>
      </section>

      <div class="tiles" :class="{ dim: loading }">
        <div class="tile">
          <span class="small muted">Потрачено на покупки</span>
          <b class="v">{{ rub(data.spent) }}</b>
          <span v-if="data.unpriced_purchases" class="small muted">ещё {{ data.unpriced_purchases }} {{ plural(data.unpriced_purchases, "покупка", "покупки", "покупок") }} без цены</span>
        </div>
        <div class="tile">
          <span class="small muted">Ушло в еду</span>
          <b class="v">{{ rub(data.eaten_value) }}</b>
          <span class="small muted">приготовлено и съедено из запасов</span>
        </div>
        <div class="tile">
          <span class="small muted">Выброшено</span>
          <b class="v" :class="{ over: num(data.wasted_value) > 0 }">{{ rub(data.wasted_value) }}</b>
          <span class="small muted">испортилось, недостачи, остатки кастрюль</span>
        </div>
      </div>

      <div v-if="empty" class="card empty">
        За этот месяц покупок с ценой нет. Цену удобно вписывать прямо в <RouterLink to="/shopping">списке покупок</RouterLink> после «куплено».
      </div>

      <section v-if="num(data.snack_spent) > 0 || data.snack_quota" class="card">
        <h2>Снеки и сладкое</h2>
        <div class="sum"><b class="big">{{ rub(data.snack_spent) }}</b>
          <span v-if="data.snack_quota" class="small muted">квота {{ rub(data.snack_quota) }} в неделю</span></div>
        <p class="small muted">Категории снеков и квота — в <RouterLink to="/family">«Семья → Планировщик»</RouterLink>.</p>
      </section>

      <section v-if="data.by_category.length" class="card">
        <h2>Траты по категориям</h2>
        <div v-for="c in data.by_category" :key="c.name" class="cat">
          <div class="sum small"><span>{{ c.name }}</span><b>{{ rub(c.spent) }}</b></div>
          <div class="bar thin"><i class="spent" :style="{ width: (num(c.spent) / maxCat) * 100 + '%' }"></i></div>
        </div>
      </section>

      <section v-if="data.waste.length" class="card">
        <h2>Что выбросили</h2>
        <div class="waste">
          <div v-for="(w, i) in data.waste" :key="i" class="wrow">
            <span class="grow">{{ w.name }} <span class="muted small">· {{ w.reason }}</span></span><b>{{ rub(w.value) }}</b>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.money { display: flex; flex-direction: column; gap: 14px; max-width: 760px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
h1 { font-size: 32px; color: var(--rim); }
h2 { font-size: 18px; }
p { margin: 0; }
.months { display: flex; align-items: center; gap: 4px; }
.mt { min-width: 150px; text-align: center; }
.nav { min-width: 44px; padding: 0; font-size: 22px; }
.dim { opacity: 0.6; transition: opacity 0.2s; }
.budget { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
.bh { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.inline { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.bi { width: 160px; }
.block { flex-basis: 100%; }
.sum { display: flex; align-items: baseline; justify-content: space-between; gap: 8px 12px; flex-wrap: wrap; }
.big { font-size: 20px; }
.left { color: var(--muted); }
.over { color: var(--tomato); }
.bar { position: relative; display: flex; height: 14px; border-radius: 999px; background: var(--enamel-2); border: 1px solid var(--line); overflow: hidden; }
.bar.thin { height: 8px; }
.bar i { display: block; height: 100%; }
.bar .spent { background: var(--rim); }
.bar .spent.over { background: var(--tomato); }
/* прогноз по плану — «карандашом»: то, что приложение предполагает, а не уже случилось */
.bar .plan { background: repeating-linear-gradient(-45deg, var(--graphite-soft) 0 4px, transparent 4px 8px); border-left: 1.5px dashed var(--graphite); }
.bar .plan.over { background: repeating-linear-gradient(-45deg, color-mix(in srgb, var(--tomato) 35%, transparent) 0 4px, transparent 4px 8px); }
.limit { position: absolute; top: -1px; bottom: -1px; width: 2px; background: var(--ink); }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }

.tile, .card { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); }
.card { gap: 10px; }
.v { font-size: 26px; }
.cat { display: flex; flex-direction: column; gap: 4px; }
.waste { display: flex; flex-direction: column; }
.wrow { display: flex; align-items: baseline; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line); }
.wrow:first-child { border-top: 0; }
.grow { flex: 1; min-width: 0; }
.empty { color: var(--muted); }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
@media (max-width: 600px) {
  .tiles { grid-template-columns: 1fr; gap: 8px; }
  .tile { display: grid; grid-template-columns: 1fr auto; align-items: baseline; gap: 2px 10px; padding: 10px 14px; }
  .tile .v { grid-row: 1; grid-column: 2; font-size: 20px; }
  .tile > span:last-child:not(:first-child) { grid-column: 1 / -1; }
}</style>
