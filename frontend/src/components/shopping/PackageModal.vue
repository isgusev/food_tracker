<script setup lang="ts">
// У товара нет упаковки — округлять покупку не до чего: спросим, сколько в пачке (для всех брендов товара).
import { ref } from "vue";
import { api, ok } from "../../api/client";
import type { Line } from "../../shopping";
import { UNIT_LABEL, fmtQty, num } from "../../util";
import ModalSheet from "../ModalSheet.vue";

const props = defineProps<{ line: Line }>();
const emit = defineEmits<{ close: []; saved: [] }>();
const amount = ref<number | string>("");
const busy = ref(false);
const error = ref("");

async function save() {
  if (!(num(amount.value) > 0)) { error.value = "Укажите, сколько в одной упаковке"; return; }
  error.value = "";
  busy.value = true;
  try {
    await ok(api.POST("/api/v1/products/{product_id}/packages", { params: { path: { product_id: props.line.product_id } }, body: { amount: num(amount.value) } }));
    emit("saved");
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet :title="'Упаковка: ' + line.product_name" @close="emit('close')">
    <p class="small muted">Сейчас нужно {{ fmtQty(line.needed, line.unit) }}. Укажите, сколько в одной упаковке, —
      покупка округлится до целых упаковок (для всех брендов этого товара).</p>
    <label class="field"><span class="lbl">В одной упаковке, {{ UNIT_LABEL[line.unit] }}</span>
      <input v-model="amount" type="number" min="0.1" step="any" inputmode="decimal" placeholder="930" autofocus @keydown.enter="save"></label>
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy" @click="save">Сохранить и пересчитать</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.err { color: var(--tomato); }
</style>
