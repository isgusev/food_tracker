<script setup lang="ts">
// Быстрая инвентаризация: по каждому товару (кроме базовых) «так и есть / нет / другое количество».
// Отправляем только изменённое и «так и есть» у товаров с «учёт сбился» (подтверждаем записанное).
import { ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast, toastError } from "../../session";
import { fmtQty, num } from "../../util";
import ModalSheet from "../ModalSheet.vue";

type StockItem = Schemas["StockItem"];
const props = defineProps<{ items: StockItem[] }>();
const emit = defineEmits<{ close: []; saved: [list: StockItem[] | null] }>();

const rows = ref(props.items.filter((i) => !i.is_staple)
  .map((i) => ({ ...i, mode: "ok" as "ok" | "none" | "set", value: num(i.remaining) as number | string })));
const busy = ref(false);

async function save() {
  busy.value = true;
  let last: StockItem[] | null = null;
  try {
    for (const r of rows.value) {
      if (r.mode === "ok" && !r.needs_check) continue;
      const quantity = r.mode === "none" ? 0 : r.mode === "ok" ? num(r.remaining) : num(r.value);
      last = await ok(api.POST("/api/v1/stock/items/{product_id}/inventory", { params: { path: { product_id: r.product_id } }, body: { quantity } }));
    }
    toast("Инвентаризация сохранена");
    emit("saved", last);
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet title="Быстрая инвентаризация" wide @close="emit('close')">
    <p class="tiny muted">Пройдитесь по полкам: если всё как записано — ничего не трогайте.</p>
    <p v-if="!rows.length" class="muted">Запасы пусты.</p>
    <div v-else class="list">
      <div v-for="r in rows" :key="r.item_key" class="r">
        <div class="grow"><b>{{ r.name }}</b>
          <div class="tiny muted">записано {{ fmtQty(r.remaining, r.unit) }}<span v-if="r.needs_check" class="warn"> · учёт сбился</span></div></div>
        <div class="seg" role="group" :aria-label="r.name">
          <button :class="{ on: r.mode === 'ok' }" :aria-pressed="r.mode === 'ok'" @click="r.mode = 'ok'">Так и есть</button>
          <button :class="{ on: r.mode === 'none' }" :aria-pressed="r.mode === 'none'" @click="r.mode = 'none'">Нет</button>
          <button :class="{ on: r.mode === 'set' }" :aria-pressed="r.mode === 'set'" @click="r.mode = 'set'">Другое</button>
        </div>
        <input v-if="r.mode === 'set'" v-model="r.value" type="number" min="0" step="any" inputmode="decimal" class="n3" :aria-label="'Сколько есть: ' + r.name">
      </div>
    </div>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy" @click="save">Сохранить</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
.list { display: flex; flex-direction: column; }
.r { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 0; border-top: 1px solid var(--line); }
.r:first-child { border-top: 0; }
.grow { flex: 1; min-width: 160px; }
.warn { color: var(--cook); }
.seg { display: inline-flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); }
.seg button { min-height: 38px; border: 0; padding: 0 12px; color: var(--ink); font-weight: 500; font-size: 14px; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
.n3 { width: 100px; }
</style>
