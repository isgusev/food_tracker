<script setup lang="ts">
// Черновик продукта (Open Food Facts или вручную): проверить и дополнить перед сохранением в справочник.
// Поменяли название найденного товара — его штрихкод сбрасывается (это уже другой товар);
// штрихкод, введённый руками или сканом, это правило отменяет.
import { ref, useId, watch } from "vue";
import { catalog } from "../../catalog";
import type { Draft } from "../../drafts";
import BarcodeScanner from "./BarcodeScanner.vue";
import KbjuInputs from "./KbjuInputs.vue";

const draft = defineModel<Draft>({ required: true });
/** КБЖУ можно оставить пустыми (покупки, чек) — спросим при первом использовании в плане или рецепте. */
defineProps<{ kbjuOptional?: boolean }>();

const listId = useId();
const scanning = ref(false);
const barcodeReset = ref(false);

watch(() => draft.value.name, (name) => {
  const d = draft.value;
  if (d.searchBarcode && d.barcode === d.searchBarcode && (name || "").trim() !== (d.searchName || "").trim()) {
    d.barcode = null;
    barcodeReset.value = true;
  }
});
watch(draft, () => { barcodeReset.value = false; });

function manualBarcode() { draft.value.searchBarcode = null; barcodeReset.value = false; }
function onScan(code: string) {
  scanning.value = false;
  draft.value.barcode = code;
  manualBarcode();
}
</script>

<template>
  <div class="draft">
    <p class="tiny note">
      <template v-if="draft.source === 'manual'">Новый продукт: название, категория и КБЖУ на 100 г с упаковки. Он сохранится в справочник.</template>
      <template v-else>Из Open Food Facts — проверьте цифры с упаковки. Продукт сохранится в справочник.</template>
    </p>
    <label>Название<input v-model="draft.name" placeholder="Пита ливанская"></label>
    <div class="two">
      <label>Бренд<input v-model="draft.brand" placeholder="Без бренда"></label>
      <label>Категория<input v-model="draft.category" :list="listId">
        <datalist :id="listId"><option v-for="c in catalog.productCategories" :key="c.id" :value="c.name" /></datalist></label>
    </div>
    <label>Производитель, если отличается от бренда<input v-model="draft.manufacturer"></label>
    <KbjuInputs v-model="draft.kbju" />
    <p v-if="kbjuOptional" class="tiny muted">КБЖУ можно не заполнять сейчас — спросим, когда добавите продукт в план или рецепт.</p>
    <div class="pkg">
      <span class="small muted">Упаковка</span>
      <input v-model.number="draft.package_amount" type="number" min="0" step="any" placeholder="—" aria-label="Размер упаковки">
      <select v-model="draft.package_unit" aria-label="Единица упаковки">
        <option value="g">г</option><option value="ml">мл</option><option value="pcs">шт</option>
      </select>
    </div>
    <label>Штрихкод (необязательно)
      <span class="code">
        <input v-model="draft.barcode" inputmode="numeric" placeholder="4600000000000" @input="manualBarcode">
        <button type="button" title="Сканировать штрихкод камерой" aria-label="Сканировать штрихкод" @click="scanning = true">📷</button>
      </span>
    </label>
    <p v-if="barcodeReset" class="tiny muted">Название изменено — штрихкод найденного товара сброшен.</p>
    <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onScan" />
  </div>
</template>

<style scoped>
.draft {
  display: flex; flex-direction: column; gap: 10px; padding: 14px; border-radius: var(--r-in);
  border: 1.5px dashed var(--graphite); background: repeating-linear-gradient(-45deg, transparent 0 6px, var(--graphite-soft) 6px 7px), var(--enamel);
}
.note { color: var(--graphite); font-style: italic; margin: 0; }
p { margin: 0; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pkg { display: flex; align-items: center; gap: 8px; }
.pkg input { width: 100px; }
.pkg select { width: 80px; }
.code { display: flex; gap: 8px; }
.code input { flex: 1; min-width: 0; }
.code button { padding: 0 12px; }
@media (max-width: 520px) { .two { grid-template-columns: 1fr; } }
</style>
