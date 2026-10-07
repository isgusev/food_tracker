// Деньги: траты за месяц против бюджета, во что ушли деньги, сколько выброшено.
import { ref, computed, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { state, loadHousehold, toast, toastError } from "../store.js";
import { fmt, fmtDayMonth, iso, n, parseIso, today } from "../util.js";

const MONTH = new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric" });
const monthStart = (s) => s.slice(0, 8) + "01";
function monthEnd(s) {
  const d = parseIso(monthStart(s));
  return iso(new Date(d.getFullYear(), d.getMonth() + 1, 0));
}
function shiftMonth(s, k) {
  const d = parseIso(monthStart(s));
  return iso(new Date(d.getFullYear(), d.getMonth() + k, 1));
}
const rub = (v) => `${fmt(v)} ₽`;

export const MoneyView = {
  setup() {
    const month = ref(monthStart(today()));
    const data = ref(null);
    const budgetInput = ref("");
    const editingBudget = ref(false);
    async function load() {
      try {
        data.value = await api.get("/finance/summary", { start_date: month.value, end_date: monthEnd(month.value) });
        budgetInput.value = data.value.monthly_budget != null ? n(data.value.monthly_budget) : "";
      } catch (e) { toastError(e); }
    }
    watch(month, load);
    onMounted(load);

    const isCurrent = computed(() => month.value === monthStart(today()));
    const budget = computed(() => (data.value?.monthly_budget != null ? n(data.value.monthly_budget) : null));
    const spent = computed(() => n(data.value?.spent));
    const projected = computed(() => spent.value + (isCurrent.value ? n(data.value?.planned_to_buy) : 0));
    const pct = (v) => (budget.value ? Math.min(100, (v / budget.value) * 100) : 0);
    const maxCat = computed(() => Math.max(1, ...(data.value?.by_category || []).map((c) => n(c.spent))));

    async function saveBudget() {
      try {
        await api.put("/finance/budget", { monthly_budget: budgetInput.value === "" ? null : n(budgetInput.value) });
        editingBudget.value = false;
        toast("Бюджет сохранён");
        await Promise.all([load(), loadHousehold()]);
      } catch (e) { toastError(e); }
    }

    return {
      month, data, budget, spent, projected, pct, maxCat, isCurrent, budgetInput, editingBudget, saveBudget,
      prev: () => (month.value = shiftMonth(month.value, -1)),
      next: () => (month.value = shiftMonth(month.value, 1)),
      title: computed(() => { const t = MONTH.format(parseIso(month.value)); return t.charAt(0).toUpperCase() + t.slice(1); }),
      rub, fmt, n, fmtDayMonth,
    };
  },
  template: `
    <div class="stack" style="max-width: 860px">
      <div class="page-head" style="margin: 0">
        <div class="row">
          <h1>Деньги</h1>
          <div class="row tight">
            <button class="icon" @click="prev" aria-label="Предыдущий месяц">‹</button>
            <span style="min-width: 140px; text-align: center">{{ title }}</span>
            <button class="icon" @click="next" aria-label="Следующий месяц" :disabled="isCurrent">›</button>
          </div>
        </div>
      </div>

      <template v-if="data">
        <div class="card stack">
          <div class="row between">
            <h2>Бюджет на продукты</h2>
            <button class="sm ghost" @click="editingBudget = !editingBudget">{{ budget == null ? 'Задать' : 'Изменить' }}</button>
          </div>
          <div v-if="editingBudget" class="row">
            <input type="number" min="0" step="100" v-model="budgetInput" placeholder="₽ в месяц" style="width: 160px">
            <button class="sm primary" @click="saveBudget">Сохранить</button>
          </div>
          <template v-if="budget != null">
            <div class="row between small">
              <span>Потрачено <b class="num">{{ rub(spent) }}</b> из <span class="num">{{ rub(budget) }}</span></span>
              <span class="num" :style="{ color: spent > budget ? 'var(--danger)' : 'var(--muted)' }">
                {{ spent > budget ? 'перерасход ' + rub(spent - budget) : 'осталось ' + rub(budget - spent) }}</span>
            </div>
            <div class="meter" style="height: 10px; position: relative" :title="'Потрачено ' + rub(spent)">
              <i :style="{ width: pct(spent) + '%', background: spent > budget ? 'var(--danger)' : 'var(--accent)' }"></i>
            </div>
            <div v-if="isCurrent && n(data.planned_to_buy) > 0" class="small muted">
              По плану ещё купить ≈ <b class="num">{{ rub(data.planned_to_buy) }}</b> → к концу месяца ≈ <b class="num" :style="{ color: projected > budget ? 'var(--danger)' : 'inherit' }">{{ rub(projected) }}</b>
              <span v-if="data.planned_unknown"> (у {{ data.planned_unknown }} позиций цена ещё неизвестна)</span>
            </div>
          </template>
          <div v-else class="small muted">Задайте месячный бюджет — будет видно, сколько осталось и хватит ли до конца месяца.</div>
        </div>

        <div class="grid-tiles">
          <div class="card stack tight">
            <span class="small muted">Потрачено на покупки</span>
            <b class="num" style="font-size: 26px">{{ rub(data.spent) }}</b>
            <span v-if="data.unpriced_purchases" class="tiny muted">ещё {{ data.unpriced_purchases }} покупок без цены</span>
          </div>
          <div class="card stack tight">
            <span class="small muted">Ушло в еду</span>
            <b class="num" style="font-size: 26px">{{ rub(data.eaten_value) }}</b>
            <span class="tiny muted">приготовлено и съедено из запасов</span>
          </div>
          <div class="card stack tight">
            <span class="small muted">Выброшено</span>
            <b class="num" style="font-size: 26px" :style="{ color: n(data.wasted_value) > 0 ? 'var(--danger)' : 'inherit' }">{{ rub(data.wasted_value) }}</b>
            <span class="tiny muted">испортилось, недостачи, остатки кастрюль</span>
          </div>
        </div>

        <div class="card stack" v-if="data.by_category.length">
          <h2>Траты по категориям</h2>
          <div v-for="c in data.by_category" :key="c.name" class="stack tight" :title="c.name + ': ' + rub(c.spent)">
            <div class="row between small"><span>{{ c.name }}</span><b class="num">{{ rub(c.spent) }}</b></div>
            <div class="meter" style="height: 8px"><i :style="{ width: (n(c.spent) / maxCat * 100) + '%', background: 'var(--accent)' }"></i></div>
          </div>
        </div>

        <div class="card stack" v-if="data.waste.length">
          <h2>Что выбросили</h2>
          <div v-for="w in data.waste" :key="w.name" class="row between small">
            <span>{{ w.name }} <span class="muted">· {{ w.reason }}</span></span><b class="num">{{ rub(w.value) }}</b>
          </div>
        </div>

        <div v-if="!n(data.spent) && !n(data.eaten_value) && !data.unpriced_purchases" class="card empty">
          За этот месяц покупок с ценой нет. Цену удобно вписывать прямо в списке покупок после «куплено».
        </div>
      </template>
    </div>`,
};
