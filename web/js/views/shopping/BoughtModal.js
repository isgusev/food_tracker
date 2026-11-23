import { ref, computed, watch, onMounted, onBeforeUnmount } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal } from "../../components.js";
import { ReceiptModal } from "../../receipts.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../../product-finder.js";
import { state, ensureCatalog, variantIndex, toast, toastError } from "../../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, local, n, startOfWeek, today, UNIT_LABEL } from "../../util.js";

// Позиция после «куплено»: количество, цена, срок
export const BoughtModal = {
  components: { Modal },
  props: { line: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const qty = ref(n(props.line.bought_quantity));
    // купили другой бренд того же товара — КБЖУ и цена пойдут по нему
    const productId = ref(props.line.product_id);
    const brands = computed(() => state.products
      .filter((p) => p.item_key === props.line.item_key)
      .map((p) => ({ id: p.id, label: `${p.brand?.name || "без бренда"} · ${p.name}` })));
    const price = ref(props.line.price != null ? n(props.line.price) : "");
    const expires = ref(props.line.expires_on || "");
    const busy = ref(false);
    async function save() {
      busy.value = true;
      try {
        const body = { quantity: n(qty.value), price: price.value === "" ? null : n(price.value), expires_on: expires.value || null };
        if (productId.value !== props.line.product_id) body.product_id = productId.value;
        const res = await api.patch(`/shopping-lists/lines/${props.line.id}`, body);
        emit("saved", res);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { qty, price, expires, busy, save, UNIT_LABEL, productId, brands };
  },
  template: `
    <Modal :title="line.product_name" @close="$emit('close')">
      <div class="grid-2">
        <label class="field"><span>Купили, {{ UNIT_LABEL[line.unit] }}</span><input type="number" min="0.1" step="any" v-model="qty"></label>
        <label class="field"><span>Цена за всё, ₽</span><input type="number" min="0" step="0.01" v-model="price" placeholder="необязательно"></label>
      </div>
      <label class="field"><span>Годен до</span><input type="date" v-model="expires"><span class="tiny">Необязательно — пригодится для напоминаний</span></label>
      <label v-if="!line.is_exact && brands.length > 1" class="field"><span>Какой бренд купили</span>
        <select v-model.number="productId"><option v-for="b in brands" :key="b.id" :value="b.id">{{ b.label }}</option></select>
        <span class="tiny">По нему посчитаются КБЖУ и цена; в следующий раз подскажем его как «обычно».</span></label>
      <template #foot>
        <button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy" @click="save">Сохранить</button>
      </template>
    </Modal>`,
};
