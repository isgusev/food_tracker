// «Честный знак»: пачки с кодами маркировки. Каждая пачка — свой срок годности
// (из кода, если производитель его туда записал, иначе — вручную); при сохранении
// пачки с одним сроком становятся одной партией, с разными — разными.
import { ref, computed } from "../vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { BarcodeScanner } from "./components.js";
import { state, toast } from "./store.js";
import { fmtDayMonth, fmtQty, n } from "./util.js";

// v-model:packs — [{ code, serial, expires_on }]; v-model:packAmount — сколько в пачке (единица товара)
export const PacksEditor = {
  components: { BarcodeScanner },
  props: { product: Object, packs: { type: Array, required: true }, packAmount: [Number, String], max: Number },
  emits: ["update:packs", "update:packAmount", "product"],
  setup(props, { emit }) {
    const scanning = ref(false);
    const unit = computed(() => props.product?.base_unit || "g");
    const packages = computed(() => props.product?.packages || []);

    async function onCode(code) {
      try {
        const m = await api.post("/stock/marks/parse", { code });
        if (m.already_registered) { toast("Эта пачка уже в запасах — её код сканировали раньше", "error"); return; }
        if (props.packs.some((p) => p.serial === m.serial && p.gtin === m.gtin)) return;
        if (props.product) {
          if ((props.product.barcode && props.product.barcode !== m.barcode) || (m.product_id && m.product_id !== props.product.id)) {
            toast(`Это код другого товара${m.product_name ? ` («${m.product_name}»)` : ""}`, "error");
            return;
          }
        } else if (m.product_id) {
          emit("product", m.product_id);
        } else {
          toast(`Товара со штрихкодом ${m.barcode} нет в справочнике — сначала добавьте его в «Продукты»`, "error", 6000);
          return;
        }
        emit("update:packs", [...props.packs, { code, gtin: m.gtin, serial: m.serial, expires_on: m.expires_on || "", fromCode: !!m.expires_on }]);
        if (!m.expires_on) toast("В коде нет срока годности — введите дату у этой пачки");
      } catch (e) { toast(e.message, "error"); }
    }
    function addManual() {
      const last = props.packs[props.packs.length - 1];
      emit("update:packs", [...props.packs, { code: null, serial: null, expires_on: last?.expires_on || "", fromCode: false }]);
    }
    const setDate = (i, v) => emit("update:packs", props.packs.map((p, j) => (j === i ? { ...p, expires_on: v } : p)));
    const remove = (i) => emit("update:packs", props.packs.filter((_, j) => j !== i));

    // «2 × до 20 окт · 1 без срока»
    const summary = computed(() => {
      const g = new Map();
      for (const p of props.packs) g.set(p.expires_on || "", (g.get(p.expires_on || "") || 0) + 1);
      return [...g.entries()].sort().map(([d, c]) => `${c} × ${d ? "до " + fmtDayMonth(d) : "без срока"}`).join(" · ");
    });
    const total = computed(() => n(props.packAmount) * props.packs.length);
    const overMax = computed(() => props.max != null && total.value > n(props.max) + 0.05);
    return { scanning, unit, packages, onCode, addManual, setDate, remove, summary, total, overMax, fmtQty, fmtDayMonth };
  },
  template: `
    <div class="stack tight">
      <div class="row">
        <button class="primary sm" @click="scanning = true">📷 Сканировать пачки</button>
        <button class="sm" @click="addManual">+ Пачка без кода</button>
      </div>
      <div class="row small">
        <span class="muted">В одной пачке</span>
        <select v-if="packages.length" :value="packAmount" @change="$emit('update:packAmount', Number($event.target.value))" style="width: auto">
          <option v-for="pk in packages" :key="pk.id" :value="Number(pk.amount)">{{ fmtQty(pk.amount, unit) }}</option>
        </select>
        <input type="number" min="0.1" step="any" :value="packAmount" style="width: 90px"
               @input="$emit('update:packAmount', $event.target.value)" aria-label="Сколько в одной пачке">
        <span class="muted">{{ unit === 'pcs' ? 'шт' : unit === 'ml' ? 'мл' : 'г' }}</span>
      </div>
      <div v-if="packs.length" class="card flush">
        <div class="row between small" style="padding: 8px 12px; border-bottom: 1px solid var(--border)">
          <b>{{ packs.length }} пач. · {{ fmtQty(total, unit) }}</b><span class="muted">{{ summary }}</span>
        </div>
        <div v-for="(p, i) in packs" :key="i" class="row small" style="padding: 6px 12px; flex-wrap: nowrap">
          <span class="grow ellipsis">Пачка {{ i + 1 }}<span class="muted"> · {{ p.code ? 'код …' + (p.serial || '').slice(-4) : 'без кода' }}</span></span>
          <span v-if="p.fromCode" class="badge ok" title="Срок прочитан из кода">до {{ fmtDayMonth(p.expires_on) }}</span>
          <input v-else type="date" :value="p.expires_on" @input="setDate(i, $event.target.value)" style="width: 150px" aria-label="Годен до">
          <button class="ghost icon" @click="remove(i)" title="Убрать пачку" aria-label="Убрать пачку">✕</button>
        </div>
      </div>
      <div v-else class="tiny muted">Сканируйте квадратный код DataMatrix на каждой пачке: срок годности подставится сам, если производитель записал его в код; одну пачку дважды добавить нельзя.</div>
      <div v-if="overMax" class="alert warn">Пачек больше, чем осталось в партии ({{ fmtQty(max, unit) }}).</div>
      <BarcodeScanner v-if="scanning" marks :count="packs.length" @close="scanning = false" @code="onCode" />
    </div>`,
};

// Пачки → тело запроса (срок у пачки без даты — null, «без срока»)
export const packsBody = (packs) => packs.map((p) => ({ code: p.code || null, expires_on: p.expires_on || null }));

// Размер пачки по умолчанию: единственная упаковка товара, иначе — подсказка
export function defaultPackAmount(product, fallback = "") {
  const pk = product?.packages || [];
  return pk.length ? Number(pk[0].amount) : fallback;
}

export const productById = (id) => state.products.find((p) => p.id === id) || null;
