import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, BarcodeScanner } from "../../components.js";
import { state, ensureCatalog, toast, toastError } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../../util.js";
import { PacksEditor, packsBody, defaultPackAmount, productById } from "../../marking.js";

// Партия → пачки со своими сроками (купили по списку, а сроки на пачках разные)
export const SplitLotModal = {
  components: { Modal, PacksEditor },
  props: { lot: Object, unit: String },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const product = computed(() => productById(props.lot.product_id));
    const packs = ref([]);
    const packAmount = ref(defaultPackAmount(product.value, n(props.lot.remaining)));
    const busy = ref(false);
    async function save() {
      if (!packs.value.length || !(n(packAmount.value) > 0)) { toast("Добавьте пачки и укажите размер пачки", "error"); return; }
      busy.value = true;
      try {
        const list = await api.post(`/stock/lots/${props.lot.id}/packs`, { pack_amount: n(packAmount.value), packs: packsBody(packs.value) });
        toast("Сроки по пачкам сохранены");
        emit("saved", list);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { product, packs, packAmount, busy, save, fmtQty, fmtDayMonth };
  },
  template: `
    <Modal title="Сроки по пачкам" @close="$emit('close')">
      <div class="small muted">Партия от {{ fmtDayMonth(lot.purchased_on) }}: осталось {{ fmtQty(lot.remaining, unit) }}.
        Пачки с другим сроком станут отдельными партиями — холодильник будет списывать сначала те, что раньше испортятся.</div>
      <PacksEditor :product="product" v-model:packs="packs" v-model:packAmount="packAmount" :max="Number(lot.remaining)" />
      <template #foot><button @click="$emit('close')">Отмена</button><button class="primary" :disabled="busy || !packs.length" @click="save">Сохранить</button></template>
    </Modal>`,
};
