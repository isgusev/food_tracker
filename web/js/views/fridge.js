// Холодильник: приготовленные блюда (кастрюли), их остатки, резерв под планы и архив.
import { ref, computed, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Picker, IngredientsEditor, Macros } from "../components.js";
import { state, ensureCatalog, recipeById, toast, toastError, variantIndex } from "../store.js";
import { fmt, fmtDateTime, fmtQty, grams, gramsToBase, n, today } from "../util.js";
import { StockTab } from "./stock.js";

export const CookModal = {
  components: { Modal, Picker, IngredientsEditor },
  props: { recipeId: Number },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const rid = ref(props.recipeId || null);
    const ingredients = ref([]);
    const cooked = ref(0);
    const busy = ref(false);
    const error = ref("");
    const recipeItems = computed(() => [...state.recipes].sort((a, b) => a.name.localeCompare(b.name, "ru")).map((r) => ({ id: r.id, label: r.name })));
    // Запасы: чего не хватит для этой готовки (списание всё равно пройдёт — с пометкой)
    const stock = ref(null);
    api.get("/stock").then((r) => { stock.value = Object.fromEntries(r.map((i) => [i.item_key, i])); }).catch(() => {});
    const shortages = computed(() => {
      if (!stock.value) return [];
      const need = new Map();
      for (const i of ingredients.value) {
        const v = variantIndex.value[i.variant_id];
        if (!v || !(n(i.weight_g) > 0)) continue;
        const key = v.product.name.toLowerCase();
        const unit = v.product.base_unit || "g";
        const prev = need.get(key) || { name: v.name, unit, qty: 0 };
        prev.qty += gramsToBase(i.weight_g, unit, v.product.piece_weight_g);
        need.set(key, prev);
      }
      const out = [];
      for (const [key, x] of need) {
        const s = stock.value[key];
        if (s?.is_staple) continue;
        const have = n(s?.remaining);
        if (have < x.qty) out.push({ ...x, have });
      }
      return out;
    });
    function fill(id) {
      const r = recipeById.value[id];
      if (!r) return;
      ingredients.value = r.template_ingredients.map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) }));
      cooked.value = n(r.estimated_cooked_weight);
    }
    if (rid.value) fill(rid.value);
    async function save() {
      error.value = "";
      if (!rid.value) { error.value = "Выберите рецепт"; return; }
      const list = ingredients.value.filter((i) => i.variant_id && n(i.weight_g) > 0);
      if (!list.length) { error.value = "Добавьте хотя бы один ингредиент"; return; }
      busy.value = true;
      try {
        await api.post(`/recipes/${rid.value}/cook`, {
          total_cooked_weight: n(cooked.value),
          ingredients: list.map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) })),
        });
        toast("Блюдо в холодильнике. Планы по этому рецепту привязаны к нему.");
        emit("saved");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return { rid, ingredients, cooked, busy, error, recipeItems, fill, save, shortages, fmtQty };
  },
  template: `
    <Modal title="Приготовить блюдо" wide @close="$emit('close')">
      <label class="field" v-if="!recipeId"><span>Рецепт</span>
        <Picker :items="recipeItems" v-model="rid" @pick="fill($event.id)" autofocus placeholder="Что готовим?" />
      </label>
      <template v-if="rid">
        <div class="small muted">Состав подставлен из рецепта — поправьте под то, что реально положили. КБЖУ кастрюли посчитается по факту.</div>
        <IngredientsEditor v-model="ingredients" :cookedWeight="cooked" />
        <div v-if="shortages.length" class="alert warn small">
          В запасах не хватает: <span v-for="(x, i) in shortages" :key="x.name">{{ i ? '; ' : '' }}{{ x.name }} — есть {{ fmtQty(x.have, x.unit) }}, нужно {{ fmtQty(x.qty, x.unit) }}</span>.
          Готовить можно — товар пометится «уточнить остаток».
        </div>
        <label class="field" style="max-width: 260px"><span>Вес готового блюда, г</span>
          <input type="number" min="1" step="any" v-model="cooked">
          <span class="tiny">Взвесьте кастрюлю за вычетом её веса</span>
        </label>
      </template>
      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy || !rid" @click="save">Приготовлено</button>
      </template>
    </Modal>`,
};

const PotModal = {
  components: { Modal, IngredientsEditor, Macros },
  props: { pot: Object, name: String },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const remaining = ref(n(props.pot.current_remaining_weight));
    const ingredients = ref(props.pot.actual_ingredients.map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) })));
    const editIngr = ref(false);
    const busy = ref(false);
    const error = ref("");
    const confirmDelete = ref(null);

    async function run(fn, msg) {
      error.value = ""; busy.value = true;
      try { await fn(); if (msg) toast(msg); emit("saved"); }
      catch (e) { error.value = e.message; }
      finally { busy.value = false; }
    }
    const saveRemaining = () => run(
      () => api.patch(`/recipes/cooking-logs/${props.pot.id}`, { current_remaining_weight: n(remaining.value) }),
      n(remaining.value) < n(props.pot.planned_g)
        ? "Остаток обновлён. Планам, которым не хватит, — снова «надо приготовить»"
        : "Остаток обновлён"
    );
    const saveIngredients = () => run(() => api.put(`/recipes/cooking-logs/${props.pot.id}/ingredients`, {
      ingredients: ingredients.value.filter((i) => i.variant_id && n(i.weight_g) > 0).map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) })),
    }), "Состав пересчитан");
    const discard = () => {
      if (!confirm(`Выбросить остаток (${grams(props.pot.current_remaining_weight)})? Блюдо уйдёт в архив, планы по нему снова станут «надо приготовить».`)) return;
      run(() => api.post(`/recipes/cooking-logs/${props.pot.id}/discard`), "Списано в архив");
    };
    async function askDelete() {
      error.value = "";
      try {
        const u = await api.get(`/recipes/cooking-logs/${props.pot.id}/usage`);
        confirmDelete.value = u;
      } catch (e) { error.value = e.message; }
    }
    const doDelete = (removeFromDiary) => run(
      () => api.del(`/recipes/cooking-logs/${props.pot.id}`, { remove_from_diary: removeFromDiary }),
      "Удалено из холодильника"
    );
    return { remaining, ingredients, editIngr, busy, error, confirmDelete, saveRemaining, saveIngredients, discard, askDelete, doDelete, grams, fmtDateTime };
  },
  template: `
    <Modal :title="name" wide @close="$emit('close')">
      <div class="row small muted">
        <span>Приготовлено {{ fmtDateTime(pot.cooked_at) }}</span>
        <span>· сырой вес {{ grams(pot.total_raw_weight) }} → готовый {{ grams(pot.total_cooked_weight) }}</span>
      </div>
      <div class="small"><span class="muted">На 100 г: </span>
        <Macros :m="{ calories: pot.calories_per_100g, proteins: pot.proteins_per_100g, fats: pot.fats_per_100g, carbs: pot.carbs_per_100g }" :digits="1" /></div>

      <div class="row" style="align-items: flex-end">
        <label class="field" style="width: 200px"><span>Осталось в кастрюле, г</span>
          <input type="number" min="0" :max="pot.total_cooked_weight" step="any" v-model="remaining"></label>
        <button :disabled="busy" @click="saveRemaining">Сохранить остаток</button>
        <span class="small muted">Запланировано: {{ grams(pot.planned_g) }}</span>
      </div>

      <div>
        <button class="sm" v-if="!editIngr" @click="editIngr = true">Изменить фактический состав…</button>
        <div v-else class="stack tight">
          <h3>Фактический состав</h3>
          <IngredientsEditor v-model="ingredients" :cookedWeight="pot.total_cooked_weight" />
          <div><button class="primary sm" :disabled="busy" @click="saveIngredients">Пересчитать КБЖУ</button></div>
        </div>
      </div>

      <div v-if="confirmDelete" class="alert warn stack tight">
        <template v-if="confirmDelete.past_dates.length">
          <div>Удалить нельзя: блюдо уже учтено в дневнике за {{ confirmDelete.past_dates.join(', ') }}. Если остаток испортился — используйте «Выбросить остаток».</div>
        </template>
        <template v-else-if="confirmDelete.current_future_dates.length">
          <div>Блюдо используется в плане на {{ confirmDelete.current_future_dates.join(', ') }}. Что сделать с этими записями?</div>
          <div class="row">
            <button class="sm" :disabled="busy" @click="doDelete(false)">Оставить в плане (надо приготовить заново)</button>
            <button class="sm danger" :disabled="busy" @click="doDelete(true)">Удалить и их</button>
          </div>
        </template>
        <template v-else>
          <div>Блюдо нигде не используется. Удалить без следа (например, добавлено по ошибке)?</div>
          <div><button class="sm danger solid" :disabled="busy" @click="doDelete(false)">Удалить</button></div>
        </template>
      </div>

      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button class="danger" :disabled="busy" @click="askDelete">Удалить…</button>
        <span class="grow"></span>
        <button :disabled="busy" @click="discard">🗑 Выбросить остаток</button>
      </template>
    </Modal>`,
};

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
    return { tab, pots, archive, cooking, opened, potName, bar, onSaved, stockKey, potCosts, grams, fmt, fmtDateTime };
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
        <div v-else class="card flush">
          <div v-for="p in pots" :key="p.id" class="list-item clickable" @click="opened = p">
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
                <span>{{ fmtDateTime(p.cooked_at) }} · {{ fmt(p.calories_per_100g) }} ккал/100 г<template v-if="potCosts[p.id]?.cost"> · {{ fmt(potCosts[p.id].cost) }} ₽{{ potCosts[p.id].complete ? '' : '+' }}</template></span>
                <span v-if="bar(p).free >= 0">Свободно {{ grams(bar(p).free) }} · в планах {{ grams(p.planned_g) }}</span>
                <span v-else style="color: var(--warn)">В планах на {{ grams(-bar(p).free) }} больше, чем осталось</span>
              </div>
            </div>
          </div>
        </div>
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
