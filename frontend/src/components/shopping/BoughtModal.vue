<script setup lang="ts">
// Купленная позиция: сколько купили, цена, срок и (если у товара несколько брендов) какой именно купили.
import { computed, ref } from "vue";
import { api, ok } from "../../api/client";
import { catalog } from "../../catalog";
import type { Line, ShopList } from "../../shopping";
import { UNIT_LABEL, num } from "../../util";
import ModalSheet from "../ModalSheet.vue";

const props = defineProps<{ line: Line }>();
const emit = defineEmits<{ close: []; saved: [list: ShopList] }>();

const qty = ref<number | string>(num(props.line.bought_quantity));
const price = ref<number | string>(props.line.price != null ? num(props.line.price) : "");
const expires = ref(props.line.expires_on || "");
// купили другой бренд того же товара — КБЖУ и цена пойдут по нему
const productId = ref(props.line.product_id);
const brands = computed(() => catalog.products
  .filter((p) => p.item_key === props.line.item_key)
  .map((p) => ({ id: p.id, label: `${p.brand?.name || "без бренда"} · ${p.name}` })));
const busy = ref(false);
const error = ref("");

async function save() {
  if (!(num(qty.value) > 0)) { error.value = "Укажите, сколько купили"; return; }
  error.value = "";
  busy.value = true;
  try {
    emit("saved", await ok(api.PATCH("/api/v1/shopping-lists/lines/{line_id}", {
      params: { path: { line_id: props.line.id } },
      body: {
        quantity: num(qty.value), price: price.value === "" ? null : num(price.value), expires_on: expires.value || null,
        ...(productId.value !== props.line.product_id ? { product_id: productId.value } : {}),
      },
    })));
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet :title="line.product_name" @close="emit('close')">
    <div class="two">
      <label class="field"><span class="lbl">Купили, {{ UNIT_LABEL[line.unit] }}</span>
        <input v-model="qty" type="number" min="0.1" step="any" inputmode="decimal"></label>
      <label class="field"><span class="lbl">Цена за всё, ₽</span>
        <input v-model="price" type="number" min="0" step="0.01" inputmode="decimal" placeholder="необязательно" @keydown.enter="save"></label>
    </div>
    <label class="field"><span class="lbl">Годен до</span><input v-model="expires" type="date">
      <span class="tiny muted">Необязательно — по нему «Холодильник» подскажет, что съесть раньше.</span></label>
    <label v-if="!line.is_exact && brands.length > 1" class="field"><span class="lbl">Какой бренд купили</span>
      <select v-model.number="productId"><option v-for="b in brands" :key="b.id" :value="b.id">{{ b.label }}</option></select>
      <span class="tiny muted">По нему посчитаются КБЖУ и цена; в следующий раз подскажем его как «обычно».</span></label>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy" @click="save">Сохранить</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.err { color: var(--tomato); margin: 0; }
</style>
