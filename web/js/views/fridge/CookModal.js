import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, Macros } from "../../components.js";
import { IngredientsEditor, resolveDraftIngredients } from "../../product-finder.js";
import { state, ensureCatalog, recipeById, toast, toastError, variantIndex } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, grams, gramsToBase, n, today } from "../../util.js";
import { StockTab } from "../stock.js";

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
    const tolerance = computed(() => (state.household?.portion_tolerance ?? 15) / 100);
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
        // недобор в пределах допуска семьи — не «не хватает» (пачка 360 г на 400 г)
        if (have < x.qty * (1 - tolerance.value)) out.push({ ...x, have });
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
      try { await resolveDraftIngredients(ingredients.value); }
      catch (e) { error.value = e.message; return; }
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
