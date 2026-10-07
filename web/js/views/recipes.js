// Рецепты: библиотека, создание/правка состава, приготовление.
import { ref, computed, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, IngredientsEditor, Macros } from "../components.js";
import { state, ensureCatalog, loadRecipes, recipeCategoryName, variantLabel, toast, toastError } from "../store.js";
import { fmt, grams, matches, n } from "../util.js";
import { CookModal } from "./fridge.js";

const RecipeModal = {
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
      cooking_time_minutes: r?.cooking_time_minutes ?? null,
      estimated_cooked_weight: n(r?.estimated_cooked_weight) || null,
      instructions: r?.instructions || "",
      ingredients: r ? r.template_ingredients.map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) })) : [{ variant_id: null, weight_g: 100 }],
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
      const ingredients = f.ingredients.filter((i) => i.variant_id && n(i.weight_g) > 0)
        .map((i) => ({ variant_id: i.variant_id, weight_g: n(i.weight_g) }));
      if (!f.name.trim()) { error.value = "Укажите название"; return; }
      if (!f.recipe_category_id) { error.value = "Выберите или создайте категорию"; return; }
      if (!ingredients.length) { error.value = "Добавьте ингредиенты"; return; }
      const body = {
        name: f.name.trim(),
        recipe_category_id: f.recipe_category_id,
        default_servings: Number(f.default_servings) || 1,
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
    return { r, editing, form, newCat, busy, error, rawTotal, addCategory, save, remove, state, recipeCategoryName, variantLabel, grams, fmt, n };
  },
  template: `
    <Modal :title="r ? r.name : 'Новый рецепт'" wide @close="$emit('close')">
      <template v-if="!editing">
        <div class="row small muted">
          <span class="badge">{{ recipeCategoryName[r.recipe_category_id] }}</span>
          <span>{{ r.default_servings }} порц.</span>
          <span>· выход {{ grams(r.estimated_cooked_weight) }} (порция ≈ {{ grams(n(r.estimated_cooked_weight) / r.default_servings) }})</span>
          <span v-if="r.cooking_time_minutes">· {{ r.cooking_time_minutes }} мин</span>
        </div>
        <div class="small"><span class="muted">На 100 г: </span>
          <Macros :m="{ calories: r.calories_per_100g, proteins: r.proteins_per_100g, fats: r.fats_per_100g, carbs: r.carbs_per_100g }" :digits="1" /></div>
        <div class="card flush">
          <table class="tbl"><tbody>
            <tr v-for="i in r.template_ingredients" :key="i.id"><td>{{ variantLabel(i.variant_id) }}</td><td class="r num">{{ grams(i.weight_g) }}</td></tr>
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
        <IngredientsEditor v-model="form.ingredients" :cookedWeight="form.estimated_cooked_weight || rawTotal" />
        <div class="grid-4">
          <label class="field"><span>Выход готового, г</span>
            <input type="number" min="1" step="any" v-model="form.estimated_cooked_weight" :placeholder="fmt(rawTotal)">
          </label>
          <label class="field"><span>Порций</span><input type="number" min="1" max="100" v-model="form.default_servings"></label>
          <label class="field"><span>Время, мин</span><input type="number" min="0" v-model="form.cooking_time_minutes"></label>
        </div>
        <div class="tiny muted">Выход ≠ сырой вес: крупы развариваются, мясо ужаривается. Если пусто — возьмём сырой вес.</div>
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

export const RecipesView = {
  components: { RecipeModal, CookModal, Macros },
  setup() {
    const q = ref("");
    const cat = ref(0);
    const opened = ref(null);
    const creating = ref(false);
    const cookId = ref(null);
    onMounted(() => ensureCatalog().catch(toastError));
    const list = computed(() => state.recipes
      .filter((r) => (!cat.value || r.recipe_category_id === cat.value) && matches(r.name, q.value))
      .sort((a, b) => a.name.localeCompare(b.name, "ru")));
    function onSaved() { opened.value = null; creating.value = false; }
    function onCook(id) { opened.value = null; cookId.value = id; }
    function cooked() { cookId.value = null; location.hash = "#/fridge"; }
    return { q, cat, list, opened, creating, cookId, onSaved, onCook, cooked, state, recipeCategoryName, fmt, grams, n };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Рецепты</h1>
        <button class="primary" @click="creating = true">+ Новый рецепт</button>
      </div>
      <div class="row" style="margin-bottom: 12px">
        <input v-model="q" placeholder="Поиск…" style="max-width: 280px">
        <select v-model.number="cat" style="max-width: 220px">
          <option :value="0">Все категории</option>
          <option v-for="c in state.recipeCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
      <div v-if="!state.recipes.length" class="card empty">Рецептов пока нет. Начните с того, что готовите чаще всего.</div>
      <div v-else class="card flush table-wrap">
        <table class="tbl">
          <thead><tr><th>Блюдо</th><th>Категория</th><th class="r">Выход</th><th class="r">ккал</th><th class="r">Б</th><th class="r">Ж</th><th class="r">У</th><th></th></tr></thead>
          <tbody>
            <tr v-for="r in list" :key="r.id" style="cursor: pointer" @click="opened = r">
              <td><b>{{ r.name }}</b><div class="tiny muted">{{ r.template_ingredients.length }} ингр. · {{ r.default_servings }} порц.</div></td>
              <td class="muted small">{{ recipeCategoryName[r.recipe_category_id] }}</td>
              <td class="r num nowrap">{{ grams(r.estimated_cooked_weight) }}</td>
              <td class="r num">{{ fmt(r.calories_per_100g) }}</td>
              <td class="r num">{{ fmt(r.proteins_per_100g, 1) }}</td>
              <td class="r num">{{ fmt(r.fats_per_100g, 1) }}</td>
              <td class="r num">{{ fmt(r.carbs_per_100g, 1) }}</td>
              <td class="r"><button class="sm" @click.stop="cookId = r.id">🍳</button></td>
            </tr>
          </tbody>
        </table>
        <div class="tiny muted" style="padding: 8px 12px">КБЖУ — на 100 г готового блюда</div>
      </div>
      <RecipeModal v-if="opened || creating" :recipe="opened" @close="opened = null; creating = false" @saved="onSaved" @cook="onCook" />
      <CookModal v-if="cookId" :recipeId="cookId" @close="cookId = null" @saved="cooked" />
    </div>`,
};
