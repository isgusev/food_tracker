<script setup lang="ts">
// Рецепты семьи: поиск (подстрока или нечётко), категории фишками, карточки с КБЖУ на 100 г готового и ценой порции.
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, ensureCatalog, recipeCategoryName } from "../../catalog";
import CookModal from "../../components/fridge/CookModal.vue";
import ImportModal from "../../components/recipes/ImportModal.vue";
import RecipeModal from "../../components/recipes/RecipeModal.vue";
import { toastError } from "../../session";
import { fmt, fmtMacro, fuzzyScore, grams, local, matches, num } from "../../util";

type Recipe = Schemas["RecipeResponse"];
const router = useRouter();
const q = ref("");
const cat = ref<number>(local.get("ft.recipeCat", 0));
const opened = ref<Recipe | null>(null);
const creating = ref(false);
const importing = ref(false);
const cookId = ref<number | null>(null);
const costs = ref<Record<number, Schemas["RecipeCost"]>>({});

const loadCosts = () => ok(api.GET("/api/v1/finance/recipe-costs"))
  .then((r) => { costs.value = Object.fromEntries(r.map((c) => [c.recipe_id, c])); }).catch(() => {});
onMounted(() => { ensureCatalog().catch(toastError); loadCosts(); });
function pickCat(id: number) { cat.value = cat.value === id ? 0 : id; local.set("ft.recipeCat", cat.value); }

// категории — только те, где есть рецепты (и по числу рецептов)
const cats = computed(() => {
  const count = new Map<number, number>();
  for (const r of catalog.recipes) count.set(r.recipe_category_id, (count.get(r.recipe_category_id) ?? 0) + 1);
  return catalog.recipeCategories.filter((c) => count.has(c.id)).map((c) => ({ ...c, n: count.get(c.id)! }));
});
const list = computed(() => catalog.recipes
  .filter((r) => (!cat.value || r.recipe_category_id === cat.value) && (matches(r.name, q.value) || fuzzyScore(q.value, r.name) >= 0.6))
  .sort((a, b) => (q.value ? fuzzyScore(q.value, b.name) - fuzzyScore(q.value, a.name) : 0) || a.name.localeCompare(b.name, "ru")));

function onSaved() { opened.value = null; creating.value = false; loadCosts(); }   // порции и состав меняют цену порции
function onCook(id: number) { opened.value = null; cookId.value = id; }
function cooked() { cookId.value = null; router.push("/fridge"); }
const cost = (r: Recipe) => costs.value[r.id];
</script>

<template>
  <div class="recipes">
    <header class="head">
      <h1 class="display">Рецепты</h1>
      <div class="hb">
        <button class="text" @click="importing = true">Импорт</button>
        <button class="fill" @click="creating = true">+ Новый рецепт</button>
      </div>
    </header>

    <div class="tools">
      <span class="search">
        <input v-model="q" type="search" placeholder="Найти рецепт…" aria-label="Поиск рецепта">
        <button v-if="q" class="text clear" aria-label="Очистить" @click="q = ''">✕</button>
      </span>
      <div v-if="cats.length > 1" class="cats" role="group" aria-label="Категории">
        <button v-for="c in cats" :key="c.id" class="chip" :class="{ on: cat === c.id }" :aria-pressed="cat === c.id" @click="pickCat(c.id)">
          {{ c.name }} <span class="n">{{ c.n }}</span></button>
      </div>
    </div>

    <div v-if="catalog.loaded.recipes && !catalog.recipes.length" class="empty">
      <p>Рецептов пока нет. Начните с того, что готовите чаще всего, — по ним план посчитает покупки и КБЖУ.
        Много рецептов сразу — импортом из файла.</p>
      <div class="hb">
        <button class="fill" @click="creating = true">+ Новый рецепт</button>
        <button @click="importing = true">Импорт из файла</button>
      </div>
    </div>
    <p v-else-if="catalog.loaded.recipes && !list.length" class="muted">Ничего не нашлось{{ cat ? " в этой категории" : "" }}.</p>

    <div class="grid">
      <article v-for="r in list" :key="r.id" class="card" role="button" tabindex="0" @click="opened = r" @keydown.enter="opened = r">
        <div class="top">
          <b class="name">{{ r.name }}</b>
          <span v-if="r.effort === 'special'" class="sp" title="Эдакое, по настроению">✨</span>
        </div>
        <span class="tiny muted">{{ recipeCategoryName[r.recipe_category_id] }} · {{ r.template_ingredients?.length ?? 0 }} ингр. ·
          {{ r.default_servings }} порц. по {{ grams(num(r.estimated_cooked_weight) / (r.default_servings || 1)) }}</span>
        <div class="kb">
          <span><b class="kcal">{{ fmt(r.calories_per_100g) }}</b> <span class="tiny muted">ккал/100 г</span></span>
          <span class="tiny muted">Б {{ fmtMacro(r.proteins_per_100g) }} · Ж {{ fmtMacro(r.fats_per_100g) }} · У {{ fmtMacro(r.carbs_per_100g) }}</span>
        </div>
        <div class="bot">
          <span class="small" :title="cost(r) && num(cost(r).priced_share) < 1 ? 'Цена известна не для всех ингредиентов' : 'По последним ценам покупок'">
            <template v-if="cost(r)?.per_portion">≈ {{ fmt(cost(r).per_portion) }}{{ num(cost(r).priced_share) < 1 ? "+" : "" }} ₽ за порцию</template>
            <span v-else class="muted">цена —</span></span>
          <span v-if="r.in_rotation === false" class="tiny off">не в плане</span>
          <span class="grow"></span>
          <button class="small" @click.stop="cookId = r.id">Приготовить</button>
        </div>
      </article>
    </div>
    <p v-if="list.length" class="tiny muted">КБЖУ — на 100 г готового блюда. Цена порции — по последним покупкам; «+» — известна не для всех ингредиентов.</p>

    <RecipeModal v-if="opened || creating" :recipe="opened" @close="opened = null; creating = false" @saved="onSaved" @cook="onCook" />
    <ImportModal v-if="importing" @close="importing = false; loadCosts()" />
    <CookModal v-if="cookId" :recipe-id="cookId" @close="cookId = null" @saved="cooked" />
  </div>
</template>

<style scoped>
.recipes { display: flex; flex-direction: column; gap: 14px; max-width: 1100px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
h1 { font-size: 32px; color: var(--rim); }
.hb { display: flex; gap: 8px; flex-wrap: wrap; }
p { margin: 0; }
.tools { display: flex; flex-direction: column; gap: 10px; }
.search { position: relative; max-width: 420px; }
.search input { padding-right: 44px; }
.search input::-webkit-search-cancel-button { display: none; }
.clear { position: absolute; right: 0; top: 0; min-width: 44px; padding: 0; color: var(--muted); }
.cats { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: none; }
.chip { flex: none; min-height: 36px; padding: 0 14px; font-size: 14px; font-weight: 500; border-color: var(--line); color: var(--ink); background: var(--enamel); }
.chip .n { color: var(--muted); font-weight: 400; }
.chip.on { background: var(--rim); border-color: var(--rim); color: var(--on-fill); }
.chip.on .n { color: inherit; opacity: 0.8; }
.empty { display: flex; flex-direction: column; align-items: flex-start; gap: 12px; padding: 18px; border-radius: var(--r-pot);
  background: var(--enamel); border: 1.5px solid var(--line); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.card { display: flex; flex-direction: column; gap: 6px; padding: 14px 16px; border-radius: var(--r-pot); background: var(--enamel);
  border: 1.5px solid var(--line); cursor: pointer; }
.card:hover, .card:focus-visible { border-color: var(--rim); outline: none; }
.top { display: flex; gap: 8px; align-items: baseline; }
.name { flex: 1; font-size: 16px; overflow-wrap: anywhere; }
.kb { display: flex; flex-direction: column; }
.kcal { font-family: var(--font-display); font-size: 22px; color: var(--rim); font-weight: 600; }
.bot { display: flex; align-items: center; gap: 8px; margin-top: auto; padding-top: 4px; border-top: 1px solid var(--line); }
.grow { flex: 1; }
.off { padding: 1px 8px; border-radius: 999px; border: 1px dashed var(--graphite); color: var(--muted); }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
</style>
