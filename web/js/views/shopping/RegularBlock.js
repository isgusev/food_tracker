import { ref, computed, watch, onMounted, onBeforeUnmount } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal } from "../../components.js";
import { ReceiptModal } from "../../receipts.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../../product-finder.js";
import { state, ensureCatalog, variantIndex, toast, toastError } from "../../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, local, n, startOfWeek, today, UNIT_LABEL } from "../../util.js";
import { pkgText } from "./shared.js";

// «Обычно берём» (автоплан, этап 3): товары, которые покупают почти каждую неделю, — предложение
// «карандашом»; в список попадают по «+» или «Добавить всё» (строка ведёт себя как ручная добавка).
export const RegularBlock = {
  props: { list: Object },
  emits: ["changed"],
  setup(props, { emit }) {
    const data = ref(null);
    const busy = ref(false);
    const open = ref(local.get("ft.regularOpen", true));
    watch(open, (v) => local.set("ft.regularOpen", v));
    async function load() {
      if (!props.list) return;
      try { data.value = await api.get("/shopping-list/regular", { start_date: props.list.start_date, end_date: props.list.end_date }); }
      catch { data.value = null; }
    }
    watch(() => props.list && `${props.list.id}:${props.list.updated_at}:${props.list.lines.length}`, load, { immediate: true });
    const qty = (r) => (r.package_amount && r.package_count ? n(r.package_amount) * r.package_count : n(r.to_buy));
    async function add(r) {
      busy.value = true;
      try { emit("changed", await api.post(`/shopping-lists/${props.list.id}/lines`, { product_id: r.product_id, quantity: qty(r) })); }
      catch (e) { toastError(e); } finally { busy.value = false; }
    }
    async function addAll() {
      busy.value = true;
      let res = null;
      try {
        for (const r of data.value.items) res = await api.post(`/shopping-lists/${props.list.id}/lines`, { product_id: r.product_id, quantity: qty(r) });
        toast(`Добавлено: ${data.value.items.length}`);
      } catch (e) { toastError(e); } finally { busy.value = false; if (res) emit("changed", res); }
    }
    async function never(r) {
      try { await api.patch(`/stock/items/${r.product_id}`, { regular: "never" }); toast(`«${r.name}» больше не предлагаем`); await load(); }
      catch (e) { toastError(e); }
    }
    const snacks = computed(() => data.value?.snacks);
    const quotaPct = computed(() => (snacks.value?.quota ? Math.min(100, (n(snacks.value.spent) / n(snacks.value.quota)) * 100) : 0));
    const why = (r) => (r.always ? "всегда берём" : `брали ${r.weeks_bought} из ${r.weeks} недель`) + ` · ${fmtQty(r.weekly, r.unit)} в неделю`;
    return { data, busy, open, add, addAll, never, snacks, quotaPct, why, pkgText: (r) => pkgText({ ...r, needed: r.to_buy }), fmt, n };
  },
  template: `
    <div v-if="data && (data.items.length || snacks.quota)" class="regular">
      <div class="regular-head">
        <button class="ghost regular-toggle" @click="open = !open" :aria-expanded="open">
          <span class="draft-swatch sm" aria-hidden="true"></span>
          <b>Обычно берём</b><span v-if="data.items.length" class="muted small">{{ data.items.length }}</span>
        </button>
        <span class="grow"></span>
        <button v-if="open && data.items.length > 1" class="sm" :disabled="busy" @click="addAll">+ Добавить всё</button>
      </div>
      <div v-if="snacks.quota" class="quota" :class="{ over: n(snacks.spent) >= n(snacks.quota) }">
        <span class="small">Снеки и сладкое на неделе: <b class="num">{{ fmt(snacks.spent) }}</b> из {{ fmt(snacks.quota) }} ₽</span>
        <div class="meter"><i :style="{ width: quotaPct + '%' }"></i></div>
        <span v-if="snacks.hidden" class="tiny muted">Не предлагаем {{ snacks.hidden }} — квота недели кончилась</span>
      </div>
      <template v-if="open">
        <div v-for="r in data.items" :key="r.item_key" class="regular-row">
          <div class="grow">
            <div>{{ r.name }} <span v-if="r.is_snack" class="badge">снек</span></div>
            <div class="tiny reason">{{ why(r) }}</div>
          </div>
          <span class="nowrap" style="text-align: right"><b class="num">{{ pkgText(r) }}</b>
            <div v-if="r.est_price != null" class="tiny muted num">≈ {{ fmt(r.est_price) }} ₽</div></span>
          <button class="sm" :disabled="busy" @click="add(r)" :aria-label="'Добавить: ' + r.name">+</button>
          <button class="ghost icon sm" @click="never(r)" title="Не предлагать этот товар" aria-label="Не предлагать">✕</button>
        </div>
        <div v-if="!data.items.length" class="tiny muted" style="padding: 4px 2px">Всё обычное уже в списке или дома.</div>
      </template>
    </div>`,
};
