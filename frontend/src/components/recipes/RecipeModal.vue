<script setup lang="ts">
// Рецепт: просмотр (состав, КБЖУ на 100 г готового, свойства для автоплана, инструкция) и правка.
// Новый рецепт сразу открывается в правке: 4 порции, в ротации, простое, одна пустая строка состава.
import { computed, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, loadRecipes, recipeCategoryName, variantIndex } from "../../catalog";
import { resolveDraftIngredients, type IngredientRow } from "../../drafts";
import { toast } from "../../session";
import { MEALS, MEAL_LABEL, fmt, fmtMacro, grams, num } from "../../util";
import IngredientsEditor from "../finder/IngredientsEditor.vue";
import ModalSheet from "../ModalSheet.vue";

type Recipe = Schemas["RecipeResponse"];
const props = defineProps<{ recipe: Recipe | null }>();
const emit = defineEmits<{ close: []; saved: []; cook: [id: number] }>();

const r = props.recipe;
const editing = ref(!r);
const form = ref({
  name: r?.name || "",
  recipe_category_id: r?.recipe_category_id ?? catalog.recipeCategories[0]?.id ?? null as number | null,
  default_servings: r?.default_servings || 4 as number | string,
  allow_half: !!r?.allow_half,
  in_rotation: r ? r.in_rotation !== false : true,
  effort: r?.effort || "easy",
  meal_types: r?.meal_types ? [...r.meal_types] : [] as string[],
  keeps_days: r?.keeps_days || 2 as number | string,
  is_freezable: !!r?.is_freezable,
  cooking_time_minutes: (r?.cooking_time_minutes ?? "") as number | string,
  estimated_cooked_weight: (num(r?.estimated_cooked_weight) || "") as number | string,
  instructions: r?.instructions || "",
});
const ingredients = ref<IngredientRow[]>(r
  ? (r.template_ingredients ?? []).map((i) => ({ variant_id: i.variant_id, weight_g: num(i.weight_g), exact: !!i.exact }))
  : [{ variant_id: null, weight_g: 100 }]);
const newCat = ref("");
const busy = ref(false);
const error = ref("");

const rawTotal = computed(() => ingredients.value.reduce((s, i) => s + num(i.weight_g), 0));
const cookedFor = computed(() => num(form.value.estimated_cooked_weight) || rawTotal.value);

async function addCategory() {
  const name = newCat.value.trim();
  if (!name) return;
  try {
    const c = await ok(api.POST("/api/v1/recipes/categories", { body: { name } }));
    catalog.recipeCategories.push(c);
    form.value.recipe_category_id = c.id;
    newCat.value = "";
  } catch (e) { error.value = (e as Error).message; }
}
function toggleMeal(key: string) {
  const m = form.value.meal_types;
  form.value.meal_types = m.includes(key) ? m.filter((x) => x !== key) : [...m, key];
}

async function save() {
  error.value = "";
  const f = form.value;
  if (!f.name.trim()) { error.value = "Укажите название"; return; }
  if (!f.recipe_category_id) { error.value = "Выберите или создайте категорию"; return; }
  busy.value = true;
  try {
    await resolveDraftIngredients(ingredients.value);   // новые продукты — сначала в справочник
    const rows = ingredients.value.filter((i) => i.variant_id && num(i.weight_g) > 0)
      .map((i) => ({ variant_id: i.variant_id!, weight_g: num(i.weight_g), exact: !!i.exact }));
    if (!rows.length) throw new Error("Добавьте ингредиенты");
    const body = {
      name: f.name.trim(),
      recipe_category_id: f.recipe_category_id,
      default_servings: Math.max(1, Math.round(num(f.default_servings)) || 1),
      allow_half: f.allow_half,
      in_rotation: f.in_rotation,
      effort: f.effort,
      meal_types: f.meal_types.length ? f.meal_types : null,
      keeps_days: Math.min(14, Math.max(1, Math.round(num(f.keeps_days)) || 2)),
      is_freezable: f.is_freezable,
      cooking_time_minutes: f.cooking_time_minutes === "" ? null : Math.round(num(f.cooking_time_minutes)),
      estimated_cooked_weight: cookedFor.value,
      instructions: f.instructions.trim() || null,
      ingredients: rows,
    } as Schemas["RecipeCreate"];
    if (r) await ok(api.PATCH("/api/v1/recipes/{recipe_id}", { params: { path: { recipe_id: r.id } }, body }));
    else await ok(api.POST("/api/v1/recipes/", { body }));
    await loadRecipes();
    toast(r ? "Рецепт сохранён" : "Рецепт создан");
    emit("saved");
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
async function remove() {
  if (!r || !confirm(`Удалить рецепт «${r.name}»? Приготовленные по нему блюда останутся в холодильнике.`)) return;
  try {
    await ok(api.DELETE("/api/v1/recipes/{recipe_id}", { params: { path: { recipe_id: r.id } } }));
    await loadRecipes();
    toast("Рецепт удалён");
    emit("saved");
  } catch (e) { error.value = (e as Error).message; }
}
const portion = computed(() => (r ? num(r.estimated_cooked_weight) / (r.default_servings || 1) : 0));
const mealsLine = computed(() => (r?.meal_types?.length ? r.meal_types.map((m) => MEAL_LABEL[m]?.toLowerCase()).join(", ") : "любой приём пищи"));
const ingLabel = (id: number) => { const v = variantIndex.value[id]; return v ? v.label : `#${id}`; };
const ingSub = (id: number) => { const v = variantIndex.value[id]; return v && !v.active ? "старая версия КБЖУ" : ""; };
</script>

<template>
  <ModalSheet :title="r && !editing ? r.name : r ? 'Изменить рецепт' : 'Новый рецепт'" wide @close="emit('close')">
    <!-- просмотр -->
    <template v-if="r && !editing">
      <div class="chips">
        <span class="chip">{{ recipeCategoryName[r.recipe_category_id] || "Без категории" }}</span>
        <span v-if="r.effort === 'special'" class="chip special">✨ эдакое</span>
        <span v-if="r.in_rotation === false" class="chip off">не предлагать в плане</span>
        <span v-if="r.is_freezable" class="chip">❄️ можно заморозить</span>
        <span v-if="r.allow_half" class="chip">можно половиной</span>
      </div>
      <div class="facts">
        <div><span class="k">Выход</span><b>{{ grams(r.estimated_cooked_weight) }}</b><span class="tiny muted">сырого {{ grams(r.total_raw_weight) }}</span></div>
        <div><span class="k">Порций</span><b>{{ r.default_servings }}</b><span class="tiny muted">≈ {{ grams(portion) }}</span></div>
        <div v-if="r.cooking_time_minutes"><span class="k">Время</span><b>{{ r.cooking_time_minutes }} мин</b></div>
        <div><span class="k">Хранится</span><b>{{ r.keeps_days }} дн.</b><span class="tiny muted">{{ mealsLine }}</span></div>
      </div>
      <div class="kbju inset">
        <span class="muted small">На 100 г готового</span>
        <span><b class="display kcal">{{ fmt(r.calories_per_100g) }}</b> <span class="muted">ккал</span></span>
        <span class="small">Б {{ fmtMacro(r.proteins_per_100g) }} · Ж {{ fmtMacro(r.fats_per_100g) }} · У {{ fmtMacro(r.carbs_per_100g) }}</span>
      </div>
      <section>
        <h3>Состав на всю кастрюлю</h3>
        <div v-for="i in r.template_ingredients" :key="i.id" class="ing">
          <span class="grow">{{ ingLabel(i.variant_id) }}<span v-if="i.exact" title="Покупать именно этот бренд"> 🎯</span>
            <span v-if="ingSub(i.variant_id)" class="tiny muted"> · {{ ingSub(i.variant_id) }}</span></span>
          <b>{{ grams(i.weight_g) }}</b>
        </div>
      </section>
      <section v-if="r.instructions">
        <h3>Как готовить</h3>
        <p class="instr">{{ r.instructions }}</p>
      </section>
    </template>

    <!-- правка -->
    <template v-else>
      <label class="field"><span class="lbl">Название</span><input v-model="form.name" placeholder="Борщ" autofocus></label>
      <div class="two">
        <label class="field"><span class="lbl">Категория</span>
          <select v-model.number="form.recipe_category_id">
            <option v-for="c in catalog.recipeCategories" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select></label>
        <label class="field"><span class="lbl">…или новая</span>
          <span class="inline"><input v-model="newCat" placeholder="Супы" @keydown.enter="addCategory">
            <button type="button" class="sq" :disabled="!newCat.trim()" aria-label="Добавить категорию" @click="addCategory">+</button></span></label>
      </div>

      <h3>Состав на всю кастрюлю</h3>
      <IngredientsEditor v-model="ingredients" :cooked-weight="cookedFor" exact-toggle />
      <p class="tiny muted">🎯 — в покупки именно этот бренд; без отметки подойдёт любой бренд того же товара («Кефир 3,2%»).</p>

      <div class="three">
        <label class="field"><span class="lbl">Выход готового, г</span>
          <input v-model="form.estimated_cooked_weight" type="number" min="1" step="any" inputmode="decimal" :placeholder="fmt(rawTotal)"></label>
        <label class="field"><span class="lbl">Порций</span>
          <input v-model="form.default_servings" type="number" min="1" max="100" inputmode="numeric"></label>
        <label class="field"><span class="lbl">Время, мин</span>
          <input v-model="form.cooking_time_minutes" type="number" min="0" inputmode="numeric"></label>
      </div>
      <p class="tiny muted">Выход ≠ сырой вес: крупы развариваются, мясо ужаривается. Пусто — возьмём сырой вес.</p>
      <label class="check"><input v-model="form.allow_half" type="checkbox">
        <span>Можно готовить половиной <span class="muted small">— в покупки пойдёт половина закладки, если на план её хватает</span></span></label>

      <section class="auto">
        <h3>Для автоплана</h3>
        <label class="check"><input v-model="form.in_rotation" type="checkbox"><span>Предлагать в плане</span></label>
        <label class="check"><input v-model="form.is_freezable" type="checkbox"><span>❄️ Можно заморозить</span></label>
        <div class="two">
          <label class="field"><span class="lbl">Сложность</span>
            <select v-model="form.effort"><option value="easy">Простое, на каждый день</option><option value="special">✨ Эдакое, по настроению</option></select></label>
          <label class="field"><span class="lbl">Сколько дней можно есть</span>
            <input v-model="form.keeps_days" type="number" min="1" max="14" inputmode="numeric"></label>
        </div>
        <div class="field"><span class="lbl">Когда уместно</span>
          <div class="seg-multi" role="group" aria-label="Приёмы пищи">
            <button v-for="m in MEALS" :key="m.key" type="button" :class="{ on: form.meal_types.includes(m.key) }"
                    :aria-pressed="form.meal_types.includes(m.key)" @click="toggleMeal(m.key)">{{ m.label }}</button>
          </div>
          <span class="tiny muted">Ничего не выбрано — подходит для любого приёма пищи.</span></div>
      </section>
      <label class="field"><span class="lbl">Как готовить</span><textarea v-model="form.instructions" rows="5"></textarea></label>
    </template>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <template v-if="r && !editing">
        <button class="text danger" @click="remove">Удалить</button>
        <span class="grow"></span>
        <button @click="editing = true">Изменить</button>
        <button class="fill" @click="emit('cook', r.id)">Приготовить</button>
      </template>
      <template v-else>
        <button class="text" @click="r ? (editing = false) : emit('close')">Отмена</button>
        <button class="fill" :disabled="busy" @click="save">{{ busy ? "Сохраняю…" : "Сохранить" }}</button>
      </template>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
h3 { font-size: 16px; margin-bottom: 4px; }
section { display: flex; flex-direction: column; gap: 4px; }
.grow { flex: 1; min-width: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 13px; padding: 3px 10px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); }
.chip.special { background: var(--beak-soft); color: var(--cook); }
.chip.off { border: 1px dashed var(--graphite); }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
.facts > div { display: flex; flex-direction: column; }
.k { font-size: 12px; color: var(--muted); }
.kbju { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 14px; padding: 10px 14px; }
.kcal { font-size: 28px; color: var(--rim); }
.ing { display: flex; gap: 10px; align-items: baseline; padding: 8px 0; border-top: 1px solid var(--line); }
.instr { white-space: pre-wrap; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lbl { font-size: 14px; font-weight: 600; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.three { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.inline { display: flex; gap: 6px; }
.sq { width: 44px; padding: 0; flex: none; }
.check { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }
.check input { width: 20px; height: 20px; min-height: 0; margin: 2px 0 0; accent-color: var(--rim); flex: none; }
.auto { gap: 10px; padding: 12px 14px; border-radius: var(--r-in); background: var(--enamel-2); }
.auto select, .auto input:not([type=checkbox]) { background: var(--enamel); }
.seg-multi { display: flex; flex-wrap: wrap; gap: 6px; }
.seg-multi button { min-height: 40px; padding: 0 14px; font-size: 14px; font-weight: 500; border-color: var(--line); color: var(--ink); background: var(--enamel); }
.seg-multi button.on { background: var(--rim); border-color: var(--rim); color: var(--on-fill); }
textarea { font: inherit; color: var(--ink); background: var(--enamel-2); border: 1.5px solid var(--line); border-radius: var(--r-in);
  padding: 10px 12px; width: 100%; resize: vertical; }
.err { color: var(--tomato); }
.danger { color: var(--tomato); }
@media (max-width: 600px) { .two, .three { grid-template-columns: 1fr 1fr; } .three .field:first-child { grid-column: span 2; } }
</style>
