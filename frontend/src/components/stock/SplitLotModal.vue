<script setup lang="ts">
// Партия → пачки со своими сроками (купили по списку, а сроки на пачках разные).
import { computed, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast, toastError } from "../../session";
import { dayMonthShort, fmtQty, num } from "../../util";
import ModalSheet from "../ModalSheet.vue";
import PacksEditor, { type Pack } from "./PacksEditor.vue";
import { defaultPackAmount, packsBody, productById } from "./packs";

const props = defineProps<{ lot: Schemas["LotResponse"]; unit: string }>();
const emit = defineEmits<{ close: []; saved: [list: Schemas["StockItem"][]] }>();

const product = computed(() => productById(props.lot.product_id));
const packs = ref<Pack[]>([]);
const packAmount = ref<number | string>(defaultPackAmount(product.value, num(props.lot.remaining)));
const busy = ref(false);

async function save() {
  if (!packs.value.length || !(num(packAmount.value) > 0)) { toast("Добавьте пачки и укажите размер пачки", "error"); return; }
  busy.value = true;
  try {
    const list = await ok(api.POST("/api/v1/stock/lots/{lot_id}/packs", {
      params: { path: { lot_id: props.lot.id } }, body: { pack_amount: num(packAmount.value), packs: packsBody(packs.value) } }));
    toast("Сроки по пачкам сохранены");
    emit("saved", list);
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet title="Сроки по пачкам" @close="emit('close')">
    <p class="small muted">Партия от {{ dayMonthShort(lot.purchased_on) }}: осталось {{ fmtQty(lot.remaining, unit) }}.
      Пачки с другим сроком станут отдельными партиями — холодильник будет списывать сначала те, что раньше испортятся.</p>
    <PacksEditor v-model:packs="packs" v-model:pack-amount="packAmount" :product="product" :max="num(lot.remaining)" />
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy || !packs.length" @click="save">Сохранить</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
</style>
