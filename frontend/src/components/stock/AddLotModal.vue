<script setup lang="ts">
// Добавить в запасы: продукт (поиск или штрихкод камерой) количеством или по пачкам «Честного знака».
import { computed, ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog } from "../../catalog";
import { toast, toastError } from "../../session";
import { UNIT_LABEL, num } from "../../util";
import ItemPicker, { type PickerItem } from "../ItemPicker.vue";
import ModalSheet from "../ModalSheet.vue";
import BarcodeScanner from "../finder/BarcodeScanner.vue";
import PacksEditor, { type Pack } from "./PacksEditor.vue";
import { defaultPackAmount, packsBody, productById } from "./packs";

const emit = defineEmits<{ close: []; saved: [list: Schemas["StockItem"][]] }>();

const mode = ref<"qty" | "packs">("qty");
const packs = ref<Pack[]>([]);
const packAmount = ref<number | string>("");
const productId = ref<number | null>(null);
const qty = ref<number | string>("");
const price = ref<number | string>("");
const expires = ref("");
const busy = ref(false);
const scanning = ref(false);

async function onCode(code: string) {
  scanning.value = false;
  try {
    const r = await ok(api.GET("/api/v1/products/barcode/{code}", { params: { path: { code } } }));
    if (r.source === "local" && r.product) { productId.value = r.product.id; toast(`Нашли: ${r.product.name}`); }
    else toast("Этого штрихкода нет в справочнике — добавьте продукт в «Продукты» (там подтянутся КБЖУ)", "error", 6000);
  } catch (e) { toastError(e); }
}
const items = computed<PickerItem[]>(() => catalog.products.map((p) => ({
  id: p.id, label: p.name, sub: p.brand?.name, right: UNIT_LABEL[p.base_unit || "g"] })));
const product = computed(() => productById(productId.value));
const unit = computed(() => product.value?.base_unit || "g");
watch(productId, () => { if (!num(packAmount.value)) packAmount.value = defaultPackAmount(product.value); });

const priceOrNull = () => (price.value === "" ? null : num(price.value));
async function save() {
  if (mode.value === "packs") {
    if (!productId.value || !packs.value.length || !(num(packAmount.value) > 0)) {
      toast("Выберите продукт, размер пачки и добавьте пачки", "error"); return;
    }
  } else if (!productId.value || !(num(qty.value) > 0)) { toast("Выберите продукт и количество", "error"); return; }
  busy.value = true;
  try {
    let list: Schemas["StockItem"][];
    if (mode.value === "packs") {
      list = await ok(api.POST("/api/v1/stock/lots/packs", { body: {
        product_id: productId.value!, pack_amount: num(packAmount.value), price: priceOrNull(), packs: packsBody(packs.value) } }));
      toast(`Добавлено пачек: ${packs.value.length}`);
    } else {
      list = await ok(api.POST("/api/v1/stock/lots", { body: {
        product_id: productId.value!, quantity: num(qty.value), price: priceOrNull(), expires_on: expires.value || null } }));
      toast("Добавлено в запасы");
    }
    emit("saved", list);
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet title="Добавить в запасы" @close="emit('close')">
    <div class="field">
      <span class="lbl">Продукт</span>
      <div class="row nowrap">
        <div class="grow"><ItemPicker v-model="productId as number | null" :items="items" autofocus placeholder="Что добавить…" /></div>
        <button title="По штрихкоду" aria-label="Найти по штрихкоду камерой" @click="scanning = true">📷</button>
      </div>
    </div>
    <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onCode" />
    <div class="seg" role="group" aria-label="Как добавить">
      <button :class="{ on: mode === 'qty' }" :aria-pressed="mode === 'qty'" @click="mode = 'qty'">Количеством</button>
      <button :class="{ on: mode === 'packs' }" :aria-pressed="mode === 'packs'" @click="mode = 'packs'">По пачкам «Честный знак»</button>
    </div>
    <template v-if="mode === 'qty'">
      <div class="grid2">
        <label class="field"><span class="lbl">Количество, {{ UNIT_LABEL[unit] }}</span><input v-model="qty" type="number" min="0.1" step="any" inputmode="decimal"></label>
        <label class="field"><span class="lbl">Цена, ₽</span><input v-model="price" type="number" min="0" step="0.01" inputmode="decimal" placeholder="необязательно"></label>
      </div>
      <label class="field"><span class="lbl">Годен до</span><input v-model="expires" type="date"></label>
    </template>
    <template v-else>
      <PacksEditor v-model:packs="packs" v-model:pack-amount="packAmount" :product="product" @product="productId = $event" />
      <label class="field"><span class="lbl">Цена за все пачки, ₽</span><input v-model="price" type="number" min="0" step="0.01" inputmode="decimal" placeholder="необязательно"></label>
      <span class="tiny muted">Пачки с одним сроком станут одной партией, с разными — разными (цена делится по числу пачек).</span>
    </template>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy" @click="save">{{ busy ? "Добавляю…" : "Добавить" }}</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.row { display: flex; align-items: center; gap: 8px; }
.grow { flex: 1; min-width: 0; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 480px) { .grid2 { grid-template-columns: 1fr; } }
.seg { display: inline-flex; flex-wrap: wrap; gap: 4px; padding: 3px; border-radius: var(--r-in); background: var(--enamel-2); align-self: flex-start; }
.seg button { min-height: 38px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
</style>
