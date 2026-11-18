import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { Modal, Macros } from "../../components.js";
import { IngredientsEditor, resolveDraftIngredients } from "../../product-finder.js";
import { state, ensureCatalog, loadRecipes, recipeCategoryName, variantLabel, toast, toastError } from "../../store.js";
import { MEALS, MEAL_LABEL, fmt, fuzzyScore, grams, matches, n } from "../../util.js";
import { CookModal } from "../fridge.js";

export const RecipeModal = {
  components: { Modal, IngredientsEditor, Macros },
  props: { recipe: Object },
  emits: ["close", "saved", "cook"],
  setup(props, { emit }) {
    const r = props.recipe;
    const editing = ref(!r);
    const form = ref({
      name: r?.name || "",
      recipe_category_id: r?.recipe_category_id || state.recipeCategories[0]?.id || null,
      default_servings: r?.default_servings || 4,
      allow_half: !!r?.allow_half,
      // автоплан: в ротации, простое/«эдакое», уместные приёмы пищи (пусто — любые), хранится дней, морозилка
      in_rotation: r ? r.in_rotation !== false : true,
      effort: r?.effort || "easy",
      meal_types: r?.meal_types ? [...r.meal_types] : [],
      keeps_days: r?.keeps_days || 2,
      is_freezable: !!r?.is_freezable,
      cooking_time_minutes: r?.cooking_time_minutes ?? null,
      estimated_cooked_weight: n(r?.estimated_cooked_weight) || null,
      instructions: r?.instructions || "",
      ingredients: r ? r.template_ingredients.map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g), exact: !!i.exact })) : [{ variant_id: null, weight_g: 100 }],
    });
    const newCat = ref("");
    const busy = ref(false);
    const error = ref("");

    async function addCategory() {
      if (!newCat.value.trim()) return;
      try {
        const c = await api.post("/recipes/categories", { name: newCat.value.trim() });
        state.recipeCategories.push(c);
        form.value.recipe_category_id = c.id;
        newCat.value = "";
      } catch (e) { error.value = e.message; }
    }
    const rawTotal = computed(() => form.value.ingredients.reduce((s, i) => s + n(i.weight_g), 0));
    async function save() {
      error.value = "";
      const f = form.value;
      if (!f.name.trim()) { error.value = "Укажите название"; return; }
      if (!f.recipe_category_id) { error.value = "Выберите или создайте категорию"; return; }
      busy.value = true;
      try { await resolveDraftIngredients(f.ingredients); }   // новые продукты — сначала в справочник
      catch (e) { error.value = e.message; busy.value = false; return; }
      busy.value = false;
      const ingredients = f.ingredients.filter((i) => i.variant_id && n(i.weight_g) > 0)
        .map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g), exact: !!i.exact }));
      if (!ingredients.length) { error.value = "Добавьте ингредиенты"; return; }
      const body = {
        name: f.name.trim(),
        recipe_category_id: f.recipe_category_id,
        default_servings: Number(f.default_servings) || 1,
        allow_half: !!f.allow_half,
        in_rotation: !!f.in_rotation,
        effort: f.effort,
        meal_types: f.meal_types.length ? f.meal_types : null,
        keeps_days: Math.min(14, Math.max(1, Number(f.keeps_days) || 2)),
        is_freezable: !!f.is_freezable,
        cooking_time_minutes: f.cooking_time_minutes === "" || f.cooking_time_minutes == null ? null : Number(f.cooking_time_minutes),
        estimated_cooked_weight: n(f.estimated_cooked_weight) || rawTotal.value,
        instructions: f.instructions || null,
        ingredients,
      };
      busy.value = true;
      try {
        if (r) await api.patch(`/recipes/${r.id}`, body);
        else await api.post("/recipes/", body);
        await loadRecipes();
        toast(r ? "Рецепт сохранён" : "Рецепт создан");
        emit("saved");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    async function remove() {
      if (!confirm(`Удалить рецепт «${r.name}»? Приготовленные по нему блюда останутся в холодильнике.`)) return;
      try {
        await api.del(`/recipes/${r.id}`);
        await loadRecipes();
        toast("Рецепт удалён");
        emit("saved");
      } catch (e) { error.value = e.message; }
    }
    const mealsLine = computed(() => (r?.meal_types?.length ? r.meal_types.map((m) => MEAL_LABEL[m].toLowerCase()).join(", ") : ""));
    return { MEALS, mealsLine, r, editing, form, newCat, busy, error, rawTotal, addCategory, save, remove, state, recipeCategoryName, variantLabel, grams, fmt, n };
  },
  template: `
    <Modal :title="r ? r.name : 'Новый рецепт'" wide @close="$emit('close')">
      <template v-if="!editing">
        <div class="row small muted">
          <span class="badge">{{ recipeCategoryName[r.recipe_category_id] }}</span>
          <span>{{ r.default_servings }} порц.</span>
          <span>· выход {{ grams(r.estimated_cooked_weight) }} (порция ≈ {{ grams(n(r.estimated_cooked_weight) / r.default_servings) }})</span>
          <span v-if="r.cooking_time_minutes">· {{ r.cooking_time_minutes }} мин</span>
          <span v-if="r.allow_half">· можно половиной</span>
        </div>
        <div class="row small muted">
          <span v-if="r.in_rotation === false" class="badge">не в ротации</span>
          <span v-if="r.effort === 'special'" class="badge">✨ эдакое</span>
          <span v-if="mealsLine">{{ mealsLine }}</span>
          <span>· хранится {{ r.keeps_days }} дн.</span>
          <span v-if="r.is_freezable">· ❄️ можно заморозить</span>
        </div>
        <div class="small"><span class="muted">На 100 г: </span>
          <Macros :m="{ calories: r.calories_per_100g, proteins: r.proteins_per_100g, fats: r.fats_per_100g, carbs: r.carbs_per_100g }" :digits="1" /></div>
        <div class="card flush">
          <table class="tbl"><tbody>
            <tr v-for="i in r.template_ingredients" :key="i.id"><td>{{ variantLabel(i.variant_id) }}<span v-if="i.exact" title="Именно этот бренд"> 🎯</span></td><td class="r num">{{ grams(i.weight_g) }}</td></tr>
          </tbody></table>
        </div>
        <div v-if="r.instructions" style="white-space: pre-wrap">{{ r.instructions }}</div>
      </template>

      <template v-else>
        <label class="field"><span>Название</span><input v-model="form.name" placeholder="Борщ"></label>
        <div class="grid-2">
          <label class="field"><span>Категория</span>
            <select v-model.number="form.recipe_category_id">
              <option v-for="c in state.recipeCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
          </label>
          <label class="field"><span>…или новая категория</span>
            <div class="row" style="flex-wrap: nowrap"><input v-model="newCat" placeholder="Супы" @keydown.enter="addCategory"><button class="sm" @click="addCategory">+</button></div>
          </label>
        </div>
        <h3>Состав (на всю кастрюлю)</h3>
        <IngredientsEditor v-model="form.ingredients" :cookedWeight="form.estimated_cooked_weight || rawTotal" exactToggle />
        <div class="tiny muted">🎯 — в покупки именно этот бренд; без отметки подойдёт любой бренд того же товара («Кефир 3,2%»).</div>
        <div class="grid-4">
          <label class="field"><span>Выход готового, г</span>
            <input type="number" min="1" step="any" v-model="form.estimated_cooked_weight" :placeholder="fmt(rawTotal)">
          </label>
          <label class="field"><span>Порций</span><input type="number" min="1" max="100" v-model="form.default_servings"></label>
          <label class="field"><span>Время, мин</span><input type="number" min="0" v-model="form.cooking_time_minutes"></label>
        </div>
        <div class="tiny muted">Выход ≠ сырой вес: крупы развариваются, мясо ужаривается. Если пусто — возьмём сырой вес.</div>
        <label class="row small" style="gap: 8px; cursor: pointer; flex-wrap: nowrap; align-items: flex-start"><input type="checkbox" v-model="form.allow_half">
          <span>Можно готовить половиной <span class="muted">— в покупки пойдёт половина закладки, если на план её хватает</span></span></label>
        <h3>Для автоплана</h3>
        <div class="row small" style="gap: 14px">
          <label class="row" style="gap: 6px; cursor: pointer"><input type="checkbox" v-model="form.in_rotation"> Предлагать в плане</label>
          <label class="row" style="gap: 6px; cursor: pointer"><input type="checkbox" v-model="form.is_freezable"> ❄️ Можно заморозить</label>
        </div>
        <div class="grid-2">
          <label class="field"><span>Сложность</span>
            <select v-model="form.effort"><option value="easy">Простое, на каждый день</option><option value="special">✨ Эдакое, по настроению</option></select>
          </label>
          <label class="field"><span>Сколько дней можно есть</span><input type="number" min="1" max="14" v-model="form.keeps_days"></label>
        </div>
        <div class="field"><span>Когда уместно</span>
          <div class="row small" style="gap: 12px">
            <label v-for="m in MEALS" :key="m.key" class="row" style="gap: 6px; cursor: pointer">
              <input type="checkbox" :value="m.key" v-model="form.meal_types"> {{ m.label }}</label>
          </div>
        </div>
        <div class="tiny muted">Ничего не отмечено — подходит для любого приёма пищи.</div>
        <label class="field"><span>Как готовить</span><textarea v-model="form.instructions"></textarea></label>
      </template>

      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <template v-if="!editing">
          <button class="danger" @click="remove">Удалить</button>
          <span class="grow"></span>
          <button @click="editing = true">Изменить</button>
          <button class="primary" @click="$emit('cook', r.id)">🍳 Приготовить</button>
        </template>
        <template v-else>
          <button @click="r ? (editing = false) : $emit('close')">Отмена</button>
          <button class="primary" :disabled="busy" @click="save">Сохранить</button>
        </template>
      </template>
    </Modal>`,
};
