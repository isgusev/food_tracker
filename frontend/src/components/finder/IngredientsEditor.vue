<script setup lang="ts">
// Состав блюда (рецепт, готовка, кастрюля): аккордеон — открыт один ингредиент с поиском продукта,
// остальные компактной строкой «имя / подпись / вес / Изменить / ✕»; итоги — сырой вес и КБЖУ на 100 г готового.
import { computed, ref, watch } from "vue";
import { variantIndex } from "../../catalog";
import type { IngredientRow } from "../../drafts";
import { fmt, fmtMacro, grams, num } from "../../util";
import OffDraftCard from "./OffDraftCard.vue";
import ProductFinder from "./ProductFinder.vue";

const props = defineProps<{ modelValue: IngredientRow[]; cookedWeight?: number | string; exactToggle?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [rows: IngredientRow[]] }>();

let rowSeq = 0;
watch(() => props.modelValue, (rows) => { for (const r of rows) if (!r._k) r._k = ++rowSeq; }, { immediate: true });
// сразу открыт первый незаполненный (новый рецепт начинается с пустой строки)
const openKey = ref<number | null>(props.modelValue.find((r) => !r.variant_id && !r.draft)?._k ?? null);
const focusKey = ref<number | null>(null);

function update(i: number, patch: Partial<IngredientRow>) {
  emit("update:modelValue", props.modelValue.map((r, j) => (j === i ? { ...r, ...patch } : r)));
}
function add() {
  const row: IngredientRow = { variant_id: null, weight_g: 100, draft: null, _k: ++rowSeq };
  focusKey.value = openKey.value = row._k!;
  emit("update:modelValue", [...props.modelValue, row]);
}
function remove(i: number) {
  if (props.modelValue[i]._k === openKey.value) openKey.value = null;
  emit("update:modelValue", props.modelValue.filter((_, j) => j !== i));
}
function title(r: IngredientRow): { name: string; sub: string; empty?: boolean } {
  if (r.draft) return { name: r.draft.name || "Новый продукт", sub: r.draft.source === "manual" ? "новый, заполните данные" : "из Open Food Facts" };
  const v = r.variant_id ? variantIndex.value[r.variant_id] : undefined;
  if (!v) return { name: "Продукт не выбран", sub: "", empty: true };
  return { name: v.name, sub: [v.sub, v.active ? "" : "старая версия КБЖУ", v.kbjuMissing ? "нет КБЖУ — нажмите «Изменить»" : ""].filter(Boolean).join(" · ") };
}
function per100Of(r: IngredientRow) {
  if (r.draft) { const k = r.draft.kbju; return { calories: num(k.calories), proteins: num(k.proteins), fats: num(k.fats), carbs: num(k.carbs) }; }
  return r.variant_id ? variantIndex.value[r.variant_id] ?? null : null;
}
const totals = computed(() => {
  const t = { raw: 0, calories: 0, proteins: 0, fats: 0, carbs: 0 };
  for (const r of props.modelValue) {
    const w = num(r.weight_g);
    t.raw += w;
    const v = per100Of(r);
    if (!v) continue;
    t.calories += (num(v.calories) * w) / 100; t.proteins += (num(v.proteins) * w) / 100;
    t.fats += (num(v.fats) * w) / 100; t.carbs += (num(v.carbs) * w) / 100;
  }
  return t;
});
const per100 = computed(() => {
  const cw = num(props.cookedWeight);
  if (!cw) return null;
  const k = 100 / cw, t = totals.value;
  return { calories: t.calories * k, proteins: t.proteins * k, fats: t.fats * k, carbs: t.carbs * k };
});
</script>

<template>
  <div class="ingrs">
    <div v-for="(r, i) in modelValue" :key="r._k" class="ingr" :class="{ open: r._k === openKey }">
      <div v-if="r._k !== openKey" class="line" role="button" tabindex="0" @click="openKey = r._k!" @keydown.enter="openKey = r._k!">
        <span class="what">
          <span :class="{ muted: title(r).empty }">{{ title(r).name }}</span><span v-if="r.exact" title="Покупать именно этот бренд"> 🎯</span>
          <span v-if="title(r).sub" class="sub">{{ title(r).sub }}</span>
        </span>
        <b class="w">{{ fmt(r.weight_g, num(r.weight_g) % 1 ? 1 : 0) }} г</b>
        <button class="text small" @click.stop="openKey = r._k!">Изменить</button>
        <button class="text icon" aria-label="Убрать ингредиент" @click.stop="remove(i)">✕</button>
      </div>
      <div v-else class="edit">
        <div class="row">
          <div class="find">
            <ProductFinder :model-value="r.variant_id" :draft="r.draft ?? null" :autofocus="r._k === focusKey" kbju-prompt
                           @update:model-value="update(i, { variant_id: $event })" @update:draft="update(i, { draft: $event })" />
          </div>
          <div class="qty">
            <input type="number" min="0.1" step="any" inputmode="decimal" :value="r.weight_g" aria-label="Вес, г"
                   @input="update(i, { weight_g: ($event.target as HTMLInputElement).value })">
            <span class="muted small">г</span>
            <button v-if="exactToggle" type="button" class="exact" :class="{ on: r.exact }" :aria-pressed="!!r.exact"
                    :title="r.exact ? 'Покупать именно этот бренд' : 'Подойдёт любой бренд этого товара — нажмите, если важен именно этот'"
                    @click="update(i, { exact: !r.exact })">🎯</button>
            <button class="text icon" aria-label="Убрать ингредиент" @click="remove(i)">✕</button>
          </div>
        </div>
        <OffDraftCard v-if="r.draft" :model-value="r.draft" @update:model-value="update(i, { draft: $event })" />
        <div class="done"><button class="fill small" @click="openKey = null">Готово</button></div>
      </div>
    </div>
    <button type="button" class="add" @click="add">+ Добавить ингредиент</button>
    <div class="sum small muted">
      <span>{{ modelValue.length }} ингр.</span>
      <span>Сырой вес: <b>{{ grams(totals.raw) }}</b></span>
    </div>
    <div v-if="per100" class="small">
      <span class="muted">На 100 г готового: </span><b>{{ fmt(per100.calories) }} ккал</b> · Б {{ fmtMacro(per100.proteins) }} · Ж {{ fmtMacro(per100.fats) }} · У {{ fmtMacro(per100.carbs) }}
    </div>
  </div>
</template>

<style scoped>
.ingrs { display: flex; flex-direction: column; gap: 8px; }
.ingr { border: 1.5px solid var(--line); border-radius: var(--r-in); background: var(--enamel); }
.ingr.open { border-color: var(--rim); padding: 10px; }
.line { display: flex; align-items: center; gap: 8px; padding: 6px 4px 6px 12px; cursor: pointer; }
.what { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.sub { font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.w { white-space: nowrap; }
.edit { display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; gap: 8px; align-items: flex-start; }
.find { flex: 1; min-width: 0; }
.qty { display: flex; align-items: center; gap: 6px; flex: none; }
.qty input { width: 88px; }
.icon { min-width: 44px; padding: 0; color: var(--muted); }
.exact { min-width: 44px; padding: 0; border-color: var(--line); }
.exact.on { background: var(--rim); border-color: var(--rim); }
.done { display: flex; justify-content: flex-end; }
button.small { min-height: 40px; font-size: 14px; }
.add { width: 100%; min-height: 48px; border: 2px dashed var(--rim); border-radius: var(--r-in); }
.add:hover { background: var(--rim-soft); }
.sum { display: flex; justify-content: space-between; }
@media (max-width: 600px) {
  .row { flex-direction: column; align-items: stretch; }
  .qty { justify-content: flex-end; }
}
</style>
