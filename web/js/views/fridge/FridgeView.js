import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, Macros } from "../../components.js";
import { IngredientsEditor, resolveDraftIngredients } from "../../product-finder.js";
import { state, ensureCatalog, recipeById, toast, toastError, variantIndex } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, grams, gramsToBase, n, today } from "../../util.js";
import { StockTab } from "../stock.js";
import { CookModal } from "./CookModal.js";
import { PotModal } from "./PotModal.js";

export const FridgeView = {
  components: { CookModal, PotModal, StockTab },
  setup() {
    const tab = ref("active");
    const pots = ref([]);
    const archive = ref([]);
    const cooking = ref(false);
    const opened = ref(null);
    async function load() {
      try {
        await ensureCatalog();
        [pots.value, archive.value] = await Promise.all([
          api.get("/recipes/cooking-logs"),
          api.get("/recipes/cooking-logs/archive", { include_deleted: true }),
        ]);
      } catch (e) { toastError(e); }
    }
    onMounted(load);
    const potName = (p) => recipeById.value[p.recipe_id]?.name || p.recipe_name || (p.recipe_id ? `Рецепт #${p.recipe_id}` : "Рецепт удалён");
    function bar(p) {
      const total = n(p.total_cooked_weight) || 1;
      const rem = n(p.current_remaining_weight);
      const planned = Math.min(n(p.planned_g), rem);
      return { rem: (rem / total) * 100, planned: (planned / total) * 100, plannedLeft: ((rem - planned) / total) * 100, free: rem - n(p.planned_g) };
    }
    // после готовки/правки кастрюли запасы изменились — перерисовываем вкладку «Продукты»
    const stockKey = ref(0);
    const potCosts = ref({});
    const loadCosts = () => api.get("/finance/pot-costs").then((r) => { potCosts.value = Object.fromEntries(r.map((c) => [c.pot_id, c])); }).catch(() => {});
    onMounted(loadCosts);
    function onSaved() { cooking.value = false; opened.value = null; stockKey.value++; load(); loadCosts(); }
    // обычные кастрюли и заготовки в морозилке — отдельными блоками
    const groups = computed(() => [
      { key: "fridge", title: "", list: pots.value.filter((p) => !p.is_frozen) },
      { key: "freezer", title: "❄️ Морозилка — заготовки", list: pots.value.filter((p) => p.is_frozen) },
    ].filter((g) => g.list.length));
    return { tab, pots, groups, archive, cooking, opened, potName, bar, onSaved, stockKey, potCosts, grams, fmt, fmtDateTime, fmtDayMonth, today };
  },
  template: `
    <div>
      <div class="page-head">
        <div class="row">
          <h1>Холодильник</h1>
          <div class="segmented">
            <button :class="{ on: tab === 'active' }" @click="tab = 'active'">Готовое ({{ pots.length }})</button>
            <button :class="{ on: tab === 'stock' }" @click="tab = 'stock'">Продукты</button>
            <button :class="{ on: tab === 'archive' }" @click="tab = 'archive'">Архив</button>
          </div>
        </div>
        <button class="primary" @click="cooking = true">🍳 Приготовить</button>
      </div>

      <template v-if="tab === 'active'">
        <div v-if="!pots.length" class="card empty">Холодильник пуст. Приготовьте блюдо — и планы по нему автоматически перейдут в «есть в холодильнике».</div>
        <template v-else><template v-for="g in groups" :key="g.key">
        <h3 v-if="g.title" style="margin-top: 14px">{{ g.title }}</h3>
        <div class="card flush">
          <div v-for="p in g.list" :key="p.id" class="list-item clickable" @click="opened = p">
            <div class="grow stack tight">
              <div class="row between">
                <b>{{ potName(p) }}</b>
                <span class="num">{{ grams(p.current_remaining_weight) }} <span class="muted">из {{ grams(p.total_cooked_weight) }}</span></span>
              </div>
              <div class="progress-pot" :title="'Запланировано ' + grams(p.planned_g)">
                <i :style="{ width: bar(p).rem + '%' }"></i>
                <b :style="{ left: bar(p).plannedLeft + '%', width: bar(p).planned + '%' }"></b>
              </div>
              <div class="row between small muted">
                <span>{{ fmtDateTime(p.cooked_at) }}<template v-if="p.good_until"> · <span :style="p.good_until < today() ? 'color: var(--warn)' : ''">{{ p.is_frozen ? 'годно' : 'съесть' }} до {{ fmtDayMonth(p.good_until) }}</span></template> · {{ fmt(p.calories_per_100g) }} ккал/100 г<template v-if="potCosts[p.id]?.cost"> · {{ fmt(potCosts[p.id].cost) }} ₽{{ potCosts[p.id].complete ? '' : '+' }}</template></span>
                <span v-if="bar(p).free >= 0">Свободно {{ grams(bar(p).free) }} · в планах {{ grams(p.planned_g) }}</span>
                <span v-else style="color: var(--warn)">В планах на {{ grams(-bar(p).free) }} больше, чем осталось</span>
              </div>
            </div>
          </div>
        </div>
        </template></template>
      </template>

      <StockTab v-else-if="tab === 'stock'" :key="stockKey" />

      <template v-else>
        <div v-if="!archive.length" class="card empty">Архив пуст.</div>
        <div v-else class="card flush">
          <div v-for="a in archive" :key="a.id" class="list-item">
            <div class="grow stack tight">
              <div class="row between">
                <b>{{ a.recipe_name || potName(a) }}</b>
                <span class="row tight"><span class="badge" :class="a.is_discarded ? 'danger' : 'ok'">{{ a.is_discarded ? 'выброшено' : 'доедено' }}</span></span>
              </div>
              <div class="small muted">{{ fmtDateTime(a.cooked_at) }} · {{ grams(a.total_cooked_weight) }} · {{ fmt(a.calories_per_100g) }} ккал/100 г</div>
              <div class="small" v-for="(ev, i) in a.events" :key="i">• {{ ev }}</div>
            </div>
          </div>
        </div>
      </template>

      <CookModal v-if="cooking" @close="cooking = false" @saved="onSaved" />
      <PotModal v-if="opened" :pot="opened" :name="potName(opened)" @close="opened = null" @saved="onSaved" />
    </div>`,
};
