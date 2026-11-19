<script setup lang="ts">
// «Приготовить»: рецепт → состав из шаблона (правится под то, что положили) и вес готового; предупреждение,
// чего не хватит в запасах (по ТОВАРУ — item_key, с допуском семьи). Из «Рецептов» — с заданным recipeId.
import { computed, onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, recipeById, variantIndex } from "../../catalog";
import { resolveDraftIngredients, type IngredientRow } from "../../drafts";
import { session, toast } from "../../session";
import { fmtQty, gramsToBase, num } from "../../util";
import IngredientsEditor from "../finder/IngredientsEditor.vue";
import ItemPicker, { type PickerItem } from "../ItemPicker.vue";
import ModalSheet from "../ModalSheet.vue";

const props = defineProps<{ recipeId?: number }>();
const emit = defineEmits<{ close: []; saved: [] }>();

const rid = ref<number | null>(props.recipeId ?? null);
const ingredients = ref<IngredientRow[]>([]);
const cooked = ref<number | string>("");
const busy = ref(false);
const error = ref("");
const recipeItems = computed<PickerItem[]>(() => [...catalog.recipes].sort((a, b) => a.name.localeCompare(b.name, "ru")).map((r) => ({ id: r.id, label: r.name })));

const stock = ref<Record<string, Schemas["StockItem"]> | null>(null);
onMounted(async () => {
  try { stock.value = Object.fromEntries((await ok(api.GET("/api/v1/stock"))).map((i) => [i.item_key, i])); } catch { /* подсказка необязательна */ }
});
const tolerance = computed(() => (session.household?.portion_tolerance ?? 15) / 100);
/** Чего не хватит: нужное по товару (граммы → единица товара) против остатка; недобор в пределах допуска — не «не хватает». */
const shortages = computed(() => {
  if (!stock.value) return [];
  const need = new Map<string, { name: string; unit: string; qty: number }>();
  for (const i of ingredients.value) {
    const v = i.variant_id ? variantIndex.value[i.variant_id] : undefined;
    if (!v || !(num(i.weight_g) > 0)) continue;
    const key = v.product.item_key;
    const unit = v.product.base_unit || "g";
    const prev = need.get(key) ?? { name: v.product.item?.name || v.name, unit, qty: 0 };
    prev.qty += gramsToBase(i.weight_g, unit, v.product.piece_weight_g);
    need.set(key, prev);
  }
  const out: { name: string; unit: string; qty: number; have: number }[] = [];
  for (const [key, x] of need) {
    const s = stock.value[key];
    if (s?.is_staple) continue;
    const have = num(s?.remaining);
    if (have < x.qty * (1 - tolerance.value)) out.push({ ...x, have });
  }
  return out;
});
function fill(id: number) {
  const r = recipeById.value[id];
  if (!r) return;
  ingredients.value = (r.template_ingredients ?? []).map((i) => ({ variant_id: i.variant_id, weight_g: num(i.weight_g) }));
  cooked.value = num(r.estimated_cooked_weight);
}
if (rid.value) fill(rid.value);

async function save() {
  error.value = "";
  if (!rid.value) { error.value = "Выберите рецепт"; return; }
  if (!(num(cooked.value) > 0)) { error.value = "Укажите вес готового блюда"; return; }
  try { await resolveDraftIngredients(ingredients.value); } catch (e) { error.value = (e as Error).message; return; }
  const list = ingredients.value.filter((i) => i.variant_id && num(i.weight_g) > 0);
  if (!list.length) { error.value = "Добавьте хотя бы один ингредиент"; return; }
  busy.value = true;
  try {
    await ok(api.POST("/api/v1/recipes/{recipe_id}/cook", { params: { path: { recipe_id: rid.value } }, body: {
      total_cooked_weight: num(cooked.value),
      ingredients: list.map((i) => ({ variant_id: i.variant_id!, weight_g: num(i.weight_g), exact: false })),
    } }));
    toast("Блюдо в холодильнике. Планы по этому рецепту привязаны к нему.");
    emit("saved");
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet title="Приготовить блюдо" wide @close="emit('close')">
    <div v-if="!recipeId" class="field">
      <span class="lbl">Рецепт</span>
      <ItemPicker v-model="rid as number | null" :items="recipeItems" placeholder="Что готовим?" autofocus @pick="fill(Number($event.id))" />
    </div>
    <template v-if="rid">
      <p class="small muted">Состав подставлен из рецепта — поправьте под то, что реально положили. КБЖУ кастрюли посчитается по факту.</p>
      <IngredientsEditor v-model="ingredients" :cooked-weight="cooked" />
      <div v-if="shortages.length" class="note small">
        В запасах не хватает: <template v-for="(x, i) in shortages" :key="x.name">{{ i ? "; " : "" }}{{ x.name }} — есть {{ fmtQty(x.have, x.unit) }}, нужно {{ fmtQty(x.qty, x.unit) }}</template>.
        Готовить можно — товар пометится «уточнить остаток».
      </div>
      <label class="field weight">
        <span class="lbl">Вес готового блюда, г</span>
        <input v-model="cooked" type="number" min="1" step="any" inputmode="decimal">
        <span class="tiny muted">Взвесьте кастрюлю за вычетом её веса</span>
      </label>
    </template>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy || !rid" @click="save">Приготовлено</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.weight { max-width: 260px; }
p { margin: 0; }
.note { padding: 10px 12px; border-radius: var(--r-in); background: var(--beak-soft); }
.err { color: var(--tomato); }
</style>
