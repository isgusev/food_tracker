import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, Macros } from "../../components.js";
import { IngredientsEditor, resolveDraftIngredients } from "../../product-finder.js";
import { state, ensureCatalog, recipeById, toast, toastError, variantIndex } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, grams, gramsToBase, n, today } from "../../util.js";
import { StockTab } from "../stock.js";

export const PotModal = {
  components: { Modal, IngredientsEditor, Macros },
  props: { pot: Object, name: String },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const remaining = ref(n(props.pot.current_remaining_weight));
    const ingredients = ref(props.pot.actual_ingredients.map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) })));
    const editIngr = ref(false);
    const confirmDelete = ref(null);

    const { busy, error, run } = useAction({ inline: true, done: () => emit("saved") });
    const saveRemaining = () => run(
      () => api.patch(`/recipes/cooking-logs/${props.pot.id}`, { current_remaining_weight: n(remaining.value) }),
      n(remaining.value) < n(props.pot.planned_g)
        ? (n(remaining.value) >= n(props.pot.planned_g) * (1 - (state.household?.portion_tolerance ?? 15) / 100)
          ? "Остаток обновлён. Порции в плане уменьшены пропорционально"
          : "Остаток обновлён. Планам, которым не хватит, — снова «надо приготовить»")
        : "Остаток обновлён"
    );
    const saveIngredients = () => run(async () => {
      await resolveDraftIngredients(ingredients.value);   // новые продукты — сначала в справочник
      await api.put(`/recipes/cooking-logs/${props.pot.id}/ingredients`, {
        ingredients: ingredients.value.filter((i) => i.variant_id && n(i.weight_g) > 0).map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) })),
      });
    }, "Состав пересчитан");
    // ❄️ заготовка: заморозить остаток (по умолчанию на 60 дней), поменять срок, достать
    const keepsUntil = ref(props.pot.keeps_until || "");
    const freeze = () => run(() => api.post(`/recipes/cooking-logs/${props.pot.id}/freeze`, {}), "Остаток в морозилке");
    const saveKeeps = () => run(
      () => api.post(`/recipes/cooking-logs/${props.pot.id}/freeze`, { keeps_until: keepsUntil.value || null }), "Срок заготовки сохранён");
    const unfreeze = () => run(() => api.post(`/recipes/cooking-logs/${props.pot.id}/unfreeze`), "Достали из морозилки");
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
    return { remaining, ingredients, editIngr, busy, error, confirmDelete, saveRemaining, saveIngredients, discard, askDelete, doDelete, grams, fmtDateTime,
      keepsUntil, freeze, saveKeeps, unfreeze, fmtDayMonth, today };
  },
  template: `
    <Modal :title="name" wide @close="$emit('close')">
      <div class="row small muted">
        <span>Приготовлено {{ fmtDateTime(pot.cooked_at) }}</span>
        <span>· сырой вес {{ grams(pot.total_raw_weight) }} → готовый {{ grams(pot.total_cooked_weight) }}</span>
        <span v-if="pot.good_until && !pot.is_frozen" :style="pot.good_until < today() ? 'color: var(--warn)' : ''">· съесть до {{ fmtDayMonth(pot.good_until) }}</span>
      </div>
      <div v-if="pot.is_frozen" class="row" style="align-items: flex-end">
        <label class="field" style="width: 200px"><span>❄️ Заготовка, годна до</span>
          <input type="date" :min="today()" v-model="keepsUntil"></label>
        <button :disabled="busy || !keepsUntil || keepsUntil === pot.keeps_until" @click="saveKeeps">Сохранить срок</button>
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
        <button v-if="!pot.is_frozen" :disabled="busy" @click="freeze">❄️ Заморозить остаток</button>
        <button v-else :disabled="busy" @click="unfreeze">Достать из морозилки</button>
                <button :disabled="busy" @click="discard">🗑 Выбросить остаток</button>
      </template>
    </Modal>`,
};
