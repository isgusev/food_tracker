<script setup lang="ts">
// Внеплановая покупка: тот же поиск, что в плане (справочник → штрихкод/📷 → Open Food Facts → вручную),
// количество — упаковками или вручную. КБЖУ у нового продукта можно не вносить — спросим, когда попадёт в план.
import { computed, ref, watch } from "vue";
import { api, ok } from "../../api/client";
import { catalog, variantIndex } from "../../catalog";
import { draftError, saveDraft, type Draft } from "../../drafts";
import type { ShopList } from "../../shopping";
import { UNIT_LABEL, fmtQty, num } from "../../util";
import ModalSheet from "../ModalSheet.vue";
import OffDraftCard from "../finder/OffDraftCard.vue";
import ProductFinder from "../finder/ProductFinder.vue";

const props = defineProps<{ listId: number }>();
const emit = defineEmits<{ close: []; saved: [list: ShopList] }>();

const variantId = ref<number | null>(null);
const draft = ref<Draft | null>(null);
const mode = ref<"package" | "manual">("manual");
const pkgIdx = ref(0);
const count = ref<number | string>(1);
const qty = ref<number | string>("");
const busy = ref(false);
const error = ref("");

const product = computed(() => (variantId.value ? variantIndex.value[variantId.value]?.product ?? null : null));
const unit = computed(() => (draft.value ? draft.value.package_unit || "g" : product.value?.base_unit || "g"));
// упаковки — по всем брендам товара, как при расчёте списка
const packages = computed<number[]>(() => {
  if (draft.value) return num(draft.value.package_amount) > 0 ? [num(draft.value.package_amount)] : [];
  if (!product.value) return [];
  const key = product.value.item_key;
  const all = catalog.products.filter((p) => p.item_key === key).flatMap((p) => (p.packages || []).map((pk) => num(pk.amount)));
  return [...new Set(all)].sort((a, b) => a - b);
});
watch(packages, (p) => { mode.value = p.length ? "package" : "manual"; pkgIdx.value = 0; }, { immediate: true });
const amount = computed(() => (mode.value === "package" && packages.value.length
  ? packages.value[Math.min(pkgIdx.value, packages.value.length - 1)] * Math.max(1, num(count.value))
  : num(qty.value)));

async function save() {
  error.value = "";
  if (!variantId.value && !draft.value) { error.value = "Выберите продукт"; return; }
  if (draft.value && (error.value = draftError(draft.value, { kbjuOptional: true }))) return;
  if (!(amount.value > 0)) { error.value = "Укажите, сколько купить"; return; }
  busy.value = true;
  try {
    const productId = draft.value ? (await saveDraft(draft.value)).id : product.value!.id;
    emit("saved", await ok(api.POST("/api/v1/shopping-lists/{list_id}/lines", {
      params: { path: { list_id: props.listId } }, body: { product_id: productId, quantity: amount.value },
    })));
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet title="Внеплановая покупка" @close="emit('close')">
    <div class="field"><span class="lbl">Что купить</span>
      <ProductFinder v-model="variantId" v-model:draft="draft" autofocus />
      <span v-if="!variantId && !draft" class="tiny muted">Ищем в справочнике, затем в Open Food Facts; нет нигде — «Ввести вручную».</span>
    </div>
    <OffDraftCard v-if="draft" v-model="draft" kbju-optional />
    <template v-if="variantId || draft">
      <div v-if="packages.length" class="seg" role="radiogroup" aria-label="Как указать количество">
        <button role="radio" :aria-checked="mode === 'package'" :class="{ on: mode === 'package' }" @click="mode = 'package'">Упаковками</button>
        <button role="radio" :aria-checked="mode === 'manual'" :class="{ on: mode === 'manual' }" @click="mode = 'manual'">Вручную</button>
      </div>
      <div v-if="mode === 'package' && packages.length" class="pk">
        <input v-model.number="count" type="number" min="1" step="1" inputmode="numeric" class="cnt" aria-label="Сколько упаковок">
        <span class="muted">×</span>
        <select v-if="packages.length > 1" v-model.number="pkgIdx" class="sz" aria-label="Упаковка">
          <option v-for="(p, i) in packages" :key="i" :value="i">{{ fmtQty(p, unit) }}</option>
        </select>
        <b v-else>{{ fmtQty(packages[0], unit) }}</b>
        <span class="muted">= {{ fmtQty(amount, unit) }}</span>
      </div>
      <label v-else class="field"><span class="lbl">Сколько, {{ UNIT_LABEL[unit] }}</span>
        <input v-model="qty" type="number" min="0.1" step="any" inputmode="decimal" placeholder="500" @keydown.enter="save"></label>
      <span class="tiny muted">Если этот товар уже есть в списке, количество добавится к его строке.</span>
    </template>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy" @click="save">Добавить в список</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.seg { display: inline-flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); align-self: flex-start; }
.seg button { min-height: 38px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
.pk { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.cnt { width: 72px; }
.sz { width: auto; }
.err { color: var(--tomato); margin: 0; }
</style>
