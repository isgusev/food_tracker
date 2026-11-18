import { ref, computed, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { Modal, Macros } from "../../components.js";
import { IngredientsEditor, resolveDraftIngredients } from "../../product-finder.js";
import { state, ensureCatalog, loadRecipes, recipeCategoryName, variantLabel, toast, toastError } from "../../store.js";
import { MEALS, MEAL_LABEL, fmt, fuzzyScore, grams, matches, n } from "../../util.js";
import { CookModal } from "../fridge.js";
import { RecipeModal } from "./RecipeModal.js";

export const RecipesView = {
  components: { RecipeModal, CookModal, Macros },
  setup() {
    const q = ref("");
    const cat = ref(0);
    const opened = ref(null);
    const creating = ref(false);
    const cookId = ref(null);
    const costs = ref({});
    onMounted(() => {
      ensureCatalog().catch(toastError);
      api.get("/finance/recipe-costs").then((r) => { costs.value = Object.fromEntries(r.map((c) => [c.recipe_id, c])); }).catch(() => {});
    });
    const list = computed(() => state.recipes
      .filter((r) => (!cat.value || r.recipe_category_id === cat.value) && (matches(r.name, q.value) || fuzzyScore(q.value, r.name) >= 0.6))
      .sort((a, b) => (q.value ? fuzzyScore(q.value, b.name) - fuzzyScore(q.value, a.name) : 0) || a.name.localeCompare(b.name, "ru")));
    function onSaved() { opened.value = null; creating.value = false; }
    function onCook(id) { opened.value = null; cookId.value = id; }
    function cooked() { cookId.value = null; location.hash = "#/fridge"; }
    return { q, cat, list, opened, creating, cookId, onSaved, onCook, cooked, state, recipeCategoryName, fmt, grams, n, costs };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Рецепты</h1>
        <button class="primary" @click="creating = true">+ Новый рецепт</button>
      </div>
      <div class="row" style="margin-bottom: 12px">
        <div class="clearable" style="max-width: 280px">
          <input v-model="q" placeholder="Поиск рецепта…">
          <button v-if="q" type="button" class="clear-btn" aria-label="Очистить" title="Очистить" @click="q = ''">✕</button>
        </div>
        <select v-model.number="cat" style="max-width: 220px">
          <option :value="0">Все категории</option>
          <option v-for="c in state.recipeCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>
      <div v-if="!state.recipes.length" class="card empty">Рецептов пока нет. Начните с того, что готовите чаще всего.</div>
      <div v-else class="card flush table-wrap">
        <table class="tbl">
          <thead><tr><th>Блюдо</th><th>Категория</th><th class="r">Выход</th><th class="r">ккал</th><th class="r">Б</th><th class="r">Ж</th><th class="r">У</th><th class="r" title="Оценка по последним ценам покупок">₽/порц.</th><th></th></tr></thead>
          <tbody>
            <tr v-for="r in list" :key="r.id" style="cursor: pointer" @click="opened = r">
              <td><b>{{ r.name }}</b><div class="tiny muted">{{ r.template_ingredients.length }} ингр. · {{ r.default_servings }} порц.</div></td>
              <td class="muted small">{{ recipeCategoryName[r.recipe_category_id] }}</td>
              <td class="r num nowrap">{{ grams(r.estimated_cooked_weight) }}</td>
              <td class="r num">{{ fmt(r.calories_per_100g) }}</td>
              <td class="r num">{{ fmt(r.proteins_per_100g, 1) }}</td>
              <td class="r num">{{ fmt(r.fats_per_100g, 1) }}</td>
              <td class="r num">{{ fmt(r.carbs_per_100g, 1) }}</td>
              <td class="r num" :title="costs[r.id] && n(costs[r.id].priced_share) < 1 ? 'Цена известна не для всех ингредиентов' : ''">
                <template v-if="costs[r.id]?.per_portion">{{ fmt(costs[r.id].per_portion) }}<span v-if="n(costs[r.id].priced_share) < 1" class="muted">+</span></template>
                <span v-else class="muted">—</span></td>
              <td class="r"><button class="sm" @click.stop="cookId = r.id">🍳</button></td>
            </tr>
          </tbody>
        </table>
        <div class="tiny muted" style="padding: 8px 12px">КБЖУ — на 100 г готового блюда. ₽/порц. — оценка по последним ценам покупок; «+» — цена известна не для всех ингредиентов.</div>
      </div>
      <RecipeModal v-if="opened || creating" :recipe="opened" @close="opened = null; creating = false" @saved="onSaved" @cook="onCook" />
      <CookModal v-if="cookId" :recipeId="cookId" @close="cookId = null" @saved="cooked" />
    </div>`,
};
