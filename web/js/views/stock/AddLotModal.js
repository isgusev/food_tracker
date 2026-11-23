import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, BarcodeScanner } from "../../components.js";
import { state, ensureCatalog, toast, toastError } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../../util.js";
import { PacksEditor, packsBody, defaultPackAmount, productById } from "../../marking.js";

export const AddLotModal = {
  components: { Modal, Picker, BarcodeScanner, PacksEditor },
  emits: ["close", "saved"],
  setup(_, { emit }) {
    const mode = ref("qty");          // "qty" — количеством, "packs" — по пачкам («Честный знак»)
    const packs = ref([]);
    const packAmount = ref("");
    const productId = ref(null);
    const qty = ref("");
    const price = ref("");
    const expires = ref("");
    const busy = ref(false);
    const scanning = ref(false);
    async function onCode(code) {
      scanning.value = false;
      try {
        const r = await api.get(`/products/barcode/${code}`);
        if (r.source === "local") { productId.value = r.product.id; toast(`Нашли: ${r.product.name}`); }
        else toast("Этого штрихкода нет в справочнике — добавьте продукт в «Продукты» (там подтянутся КБЖУ)", "error", 6000);
      } catch (e) { toastError(e); }
    }
    const items = computed(() => state.products.map((p) => ({ id: p.id, label: p.name, sub: p.brand?.name, right: UNIT_LABEL[p.base_unit || "g"] })));
    const unit = computed(() => state.products.find((p) => p.id === productId.value)?.base_unit || "g");
    const product = computed(() => productById(productId.value));
    watch(productId, () => { if (!n(packAmount.value)) packAmount.value = defaultPackAmount(product.value); });
    async function savePacks() {
      if (!productId.value || !packs.value.length || !(n(packAmount.value) > 0)) {
        toast("Выберите продукт, размер пачки и добавьте пачки", "error"); return;
      }
      busy.value = true;
      try {
        const res = await api.post("/stock/lots/packs", {
          product_id: productId.value, pack_amount: n(packAmount.value),
          price: price.value === "" ? null : n(price.value), packs: packsBody(packs.value),
        });
        toast(`Добавлено пачек: ${packs.value.length}`);
        emit("saved", res);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    async function save() {
      if (mode.value === "packs") return savePacks();
      if (!productId.value || !(n(qty.value) > 0)) { toast("Выберите продукт и количество", "error"); return; }
      busy.value = true;
      try {
        const res = await api.post("/stock/lots", {
          product_id: productId.value, quantity: n(qty.value),
          price: price.value === "" ? null : n(price.value), expires_on: expires.value || null,
        });
        toast("Добавлено в запасы");
        emit("saved", res);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { mode, packs, packAmount, product, productId, qty, price, expires, busy, items, unit, save, UNIT_LABEL, scanning, onCode };
  },
  template: `
    <Modal title="Добавить в запасы" @close="$emit('close')">
      <label class="field"><span>Продукт</span>
        <div class="row" style="flex-wrap: nowrap"><div class="grow"><Picker :items="items" v-model="productId" autofocus placeholder="Что добавить…" /></div>
          <button class="sm" @click="scanning = true" title="По штрихкоду">📷</button></div></label>
      <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onCode" />
      <div class="segmented">
        <button :class="{ on: mode === 'qty' }" @click="mode = 'qty'">Количеством</button>
        <button :class="{ on: mode === 'packs' }" @click="mode = 'packs'">По пачкам «Честный знак»</button>
      </div>
      <template v-if="mode === 'qty'">
        <div class="grid-2">
          <label class="field"><span>Количество, {{ UNIT_LABEL[unit] }}</span><input type="number" min="0.1" step="any" v-model="qty"></label>
          <label class="field"><span>Цена, ₽</span><input type="number" min="0" step="0.01" v-model="price" placeholder="необязательно"></label>
        </div>
        <label class="field"><span>Годен до</span><input type="date" v-model="expires"></label>
      </template>
      <template v-else>
        <PacksEditor :product="product" v-model:packs="packs" v-model:packAmount="packAmount" @product="productId = $event" />
        <label class="field"><span>Цена за все пачки, ₽</span><input type="number" min="0" step="0.01" v-model="price" placeholder="необязательно"></label>
        <span class="tiny muted">Пачки с одним сроком станут одной партией, с разными — разными (цена делится по числу пачек).</span>
      </template>
      <template #foot><button @click="$emit('close')">Отмена</button><button class="primary" :disabled="busy" @click="save">Добавить</button></template>
    </Modal>`,
};
