import { ref, computed, watch, onMounted, onBeforeUnmount } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal } from "../../components.js";
import { ReceiptModal } from "../../receipts.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../../product-finder.js";
import { state, ensureCatalog, variantIndex, toast, toastError } from "../../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, local, n, startOfWeek, today, UNIT_LABEL } from "../../util.js";

// Внеплановая покупка: тот же поиск, что в плане (справочник → штрихкод/📷 → Open Food Facts →
// вручную), количество — упаковками или вручную. КБЖУ у нового продукта можно не вносить.
export const ExtraModal = {
  components: { Modal, ProductFinder, OffDraftCard },
  props: { listId: Number },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const variantId = ref(null);
    const draft = ref(null);
    const mode = ref("manual");      // "package" | "manual"
    const pkgIdx = ref(0);
    const count = ref(1);
    const qty = ref("");
    const busy = ref(false);
    const error = ref("");
    const product = computed(() => variantIndex.value[variantId.value]?.product || null);
    const unit = computed(() => (draft.value ? draft.value.package_unit || "g" : product.value?.base_unit || "g"));
    // упаковки — по всем брендам товара, как при расчёте списка
    const packages = computed(() => {
      if (draft.value) return n(draft.value.package_amount) > 0 ? [n(draft.value.package_amount)] : [];
      if (!product.value) return [];
      const all = state.products.filter((p) => p.item_key === product.value.item_key).flatMap((p) => (p.packages || []).map((pk) => n(pk.amount)));
      return [...new Set(all)].sort((a, b) => a - b);
    });
    watch(packages, (p) => { mode.value = p.length ? "package" : "manual"; pkgIdx.value = 0; }, { immediate: true });
    const amount = computed(() => (mode.value === "package" && packages.value.length
      ? packages.value[Math.min(pkgIdx.value, packages.value.length - 1)] * Math.max(1, n(count.value))
      : n(qty.value)));
    async function save() {
      error.value = "";
      if (!variantId.value && !draft.value) { error.value = "Выберите продукт"; return; }
      if (draft.value && (error.value = draftError(draft.value, { kbjuOptional: true }))) return;
      if (!(amount.value > 0)) { error.value = "Укажите, сколько купить"; return; }
      busy.value = true;
      try {
        const productId = draft.value ? (await saveDraft(draft.value)).id : product.value.id;
        emit("saved", await api.post(`/shopping-lists/${props.listId}/lines`, { product_id: productId, quantity: amount.value }));
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return { variantId, draft, mode, pkgIdx, count, qty, busy, error, unit, packages, amount, save, fmtQty, UNIT_LABEL };
  },
  template: `
    <Modal title="Внеплановая покупка" @close="$emit('close')">
      <div class="field"><span>Что купить</span>
        <ProductFinder v-model="variantId" v-model:draft="draft" autofocus />
        <span v-if="!variantId && !draft" class="tiny muted">Ищем в справочнике, затем в Open Food Facts; нет нигде — «Ввести вручную».</span>
      </div>
      <OffDraftCard v-if="draft" :draft="draft" kbjuOptional />
      <template v-if="variantId || draft">
        <div v-if="packages.length" class="segmented">
          <button :class="{ on: mode === 'package' }" @click="mode = 'package'">Упаковками</button>
          <button :class="{ on: mode === 'manual' }" @click="mode = 'manual'">Вручную</button>
        </div>
        <div v-if="mode === 'package' && packages.length" class="row small">
          <input type="number" min="1" step="1" v-model.number="count" style="width: 64px" aria-label="Сколько упаковок">
          <span class="muted">×</span>
          <select v-if="packages.length > 1" v-model.number="pkgIdx" style="width: auto">
            <option v-for="(p, i) in packages" :key="i" :value="i">{{ fmtQty(p, unit) }}</option>
          </select>
          <b v-else>{{ fmtQty(packages[0], unit) }}</b>
          <span class="muted">= {{ fmtQty(amount, unit) }}</span>
        </div>
        <label v-else class="field"><span>Сколько, {{ UNIT_LABEL[unit] }}</span>
          <input type="number" min="0.1" step="any" v-model="qty" placeholder="500"></label>
        <span class="tiny muted">Если этот товар уже есть в списке, количество добавится к его строке.</span>
      </template>
      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot><button @click="$emit('close')">Отмена</button><button class="primary" :disabled="busy" @click="save">Добавить в список</button></template>
    </Modal>`,
};
