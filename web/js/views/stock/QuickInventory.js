import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, BarcodeScanner } from "../../components.js";
import { state, ensureCatalog, toast, toastError } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../../util.js";
import { PacksEditor, packsBody, defaultPackAmount, productById } from "../../marking.js";

// Быстрая инвентаризация: по каждому товару «так и есть / нет / другое количество»
export const QuickInventory = {
  components: { Modal },
  props: { items: Array },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const rows = ref(props.items.filter((i) => !i.is_staple).map((i) => ({ ...i, mode: "ok", value: n(i.remaining) })));
    const busy = ref(false);
    async function save() {
      busy.value = true;
      let last = null;
      try {
        for (const r of rows.value) {
          if (r.mode === "ok" && !r.needs_check) continue;
          const q = r.mode === "none" ? 0 : r.mode === "ok" ? n(r.remaining) : n(r.value);
          last = await api.post(`/stock/items/${r.product_id}/inventory`, { quantity: q });
        }
        toast("Инвентаризация сохранена");
        emit("saved", last);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { rows, busy, save, fmtQty, UNIT_LABEL };
  },
  template: `
    <Modal title="Быстрая инвентаризация" wide @close="$emit('close')">
      <div class="tiny muted">Пройдитесь по полкам: если всё как записано — ничего не трогайте.</div>
      <div class="card flush">
        <div v-for="r in rows" :key="r.item_key" class="list-item">
          <div class="grow"><b>{{ r.name }}</b><div class="tiny muted">записано {{ fmtQty(r.remaining, r.unit) }}<span v-if="r.needs_check" style="color: var(--warn)"> · учёт сбился</span></div></div>
          <div class="segmented">
            <button :class="{ on: r.mode === 'ok' }" @click="r.mode = 'ok'">Так и есть</button>
            <button :class="{ on: r.mode === 'none' }" @click="r.mode = 'none'">Нет</button>
            <button :class="{ on: r.mode === 'set' }" @click="r.mode = 'set'">Другое</button>
          </div>
          <input v-if="r.mode === 'set'" type="number" min="0" step="any" v-model="r.value" style="width: 90px">
        </div>
        <div v-if="!rows.length" class="empty">Запасы пусты.</div>
      </div>
      <template #foot><button @click="$emit('close')">Отмена</button><button class="primary" :disabled="busy" @click="save">Сохранить</button></template>
    </Modal>`,
};
