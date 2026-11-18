import { ref, computed, watch, onMounted, onBeforeUnmount } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal } from "../../components.js";
import { ReceiptModal } from "../../receipts.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../../product-finder.js";
import { state, ensureCatalog, variantIndex, toast, toastError } from "../../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, local, n, startOfWeek, today, UNIT_LABEL } from "../../util.js";

// У товара нет упаковки — округлять покупку не до чего: спросим, сколько в пачке
export const PackageModal = {
  components: { Modal },
  props: { line: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const amount = ref("");
    const busy = ref(false);
    async function save() {
      if (!(n(amount.value) > 0)) { toast("Укажите, сколько в одной упаковке", "error"); return; }
      busy.value = true;
      try {
        await api.post(`/products/${props.line.product_id}/packages`, { amount: n(amount.value) });
        emit("saved");
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { amount, busy, save, UNIT_LABEL, fmtQty, n };
  },
  template: `
    <Modal :title="'Упаковка: ' + line.product_name" @close="$emit('close')">
      <div class="small muted">Сейчас нужно {{ fmtQty(line.needed, line.unit) }}. Укажите, сколько в одной упаковке, —
        покупка округлится до целых упаковок (для всех брендов этого товара).</div>
      <label class="field"><span>В одной упаковке, {{ UNIT_LABEL[line.unit] }}</span>
        <input type="number" min="0.1" step="any" v-model="amount" placeholder="930" autofocus @keydown.enter="save"></label>
      <template #foot><button @click="$emit('close')">Отмена</button><button class="primary" :disabled="busy" @click="save">Сохранить и пересчитать</button></template>
    </Modal>`,
};
