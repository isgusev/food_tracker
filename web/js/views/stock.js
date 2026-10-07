// Холодильник → Продукты: запасы семьи по товарам (все бренды вместе).
import { ref, computed, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Picker, BarcodeScanner } from "../components.js";
import { state, ensureCatalog, toast, toastError } from "../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../util.js";

const REASON = { purchase: "покупка", manual: "добавлено", inventory: "инвентаризация", cook: "готовка", eat: "съедено", write_off: "списано" };

const AddLotModal = {
  components: { Modal, Picker, BarcodeScanner },
  emits: ["close", "saved"],
  setup(_, { emit }) {
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
    async function save() {
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
    return { productId, qty, price, expires, busy, items, unit, save, UNIT_LABEL, scanning, onCode };
  },
  template: `
    <Modal title="Добавить в запасы" @close="$emit('close')">
      <label class="field"><span>Продукт</span>
        <div class="row" style="flex-wrap: nowrap"><div class="grow"><Picker :items="items" v-model="productId" autofocus placeholder="Что добавить…" /></div>
          <button class="sm" @click="scanning = true" title="По штрихкоду">📷</button></div></label>
      <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onCode" />
      <div class="grid-2">
        <label class="field"><span>Количество, {{ UNIT_LABEL[unit] }}</span><input type="number" min="0.1" step="any" v-model="qty"></label>
        <label class="field"><span>Цена, ₽</span><input type="number" min="0" step="0.01" v-model="price" placeholder="необязательно"></label>
      </div>
      <label class="field"><span>Годен до</span><input type="date" v-model="expires"></label>
      <template #foot><button @click="$emit('close')">Отмена</button><button class="primary" :disabled="busy" @click="save">Добавить</button></template>
    </Modal>`,
};

const ItemModal = {
  components: { Modal },
  props: { item: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const it = ref(props.item);
    const actual = ref(n(props.item.remaining));
    const woQty = ref("");
    const woNote = ref("");
    const history = ref([]);
    const busy = ref(false);
    onMounted(async () => {
      try { history.value = await api.get(`/stock/items/${it.value.product_id}/history`); } catch { /* необязательно */ }
    });
    async function run(fn, msg) {
      busy.value = true;
      try {
        const list = await fn();
        toast(msg);
        emit("saved", list);
        it.value = list.find((x) => x.item_key === it.value.item_key) || { ...it.value, remaining: 0, lots: [] };
        history.value = await api.get(`/stock/items/${it.value.product_id}/history`);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    const inventory = () => run(() => api.post(`/stock/items/${it.value.product_id}/inventory`, { quantity: n(actual.value) }), "Остаток уточнён");
    const writeOff = () => n(woQty.value) > 0 && run(() => api.post(`/stock/items/${it.value.product_id}/write-off`, { quantity: n(woQty.value), note: woNote.value || null }), "Списано");
    const flags = (body, msg) => run(() => api.patch(`/stock/items/${it.value.product_id}`, body), msg);
    return { it, actual, woQty, woNote, history, busy, inventory, writeOff, flags, fmt, fmtQty, fmtDayMonth, fmtDateTime, REASON, UNIT_LABEL, n };
  },
  template: `
    <Modal :title="it.name" wide @close="$emit('close')">
      <div class="row">
        <span class="badge" v-if="it.is_staple">базовый — остаток не считаем</span>
        <span class="badge warn" v-if="it.needs_check">учёт сбился — уточните остаток</span>
        <span class="badge danger" v-if="n(it.expired) > 0">просрочено {{ fmtQty(it.expired, it.unit) }}</span>
        <span class="muted small" v-if="!it.is_staple">Сейчас: <b class="num">{{ fmtQty(it.remaining, it.unit) }}</b></span>
      </div>

      <div v-if="it.lots.length" class="card flush table-wrap">
        <table class="tbl small">
          <thead><tr><th>Партия</th><th class="r">Осталось</th><th class="r">Цена</th><th>Годен до</th></tr></thead>
          <tbody><tr v-for="l in it.lots" :key="l.id">
            <td>{{ fmtDayMonth(l.purchased_on) }} · {{ l.brand || '—' }} <span class="muted">{{ REASON[l.source] || l.source }}</span></td>
            <td class="r num">{{ fmtQty(l.remaining, it.unit) }} <span class="muted">из {{ fmtQty(l.quantity, it.unit) }}</span></td>
            <td class="r num">{{ l.price != null ? fmt(l.price, 2) + ' ₽' : '—' }}</td>
            <td>{{ l.expires_on ? fmtDayMonth(l.expires_on) : '—' }}</td>
          </tr></tbody>
        </table>
      </div>

      <div class="grid-2" v-if="!it.is_staple">
        <div class="card stack">
          <h3>Уточнить остаток</h3>
          <div class="row"><input type="number" min="0" step="any" v-model="actual" style="width: 120px"><span class="muted small">{{ UNIT_LABEL[it.unit] }}</span>
            <button class="sm primary" :disabled="busy" @click="inventory">Так и есть</button></div>
          <span class="tiny muted">Пересчитали дома — запасы станут ровно такими.</span>
        </div>
        <div class="card stack">
          <h3>Списать</h3>
          <div class="row"><input type="number" min="0.1" step="any" v-model="woQty" style="width: 110px" placeholder="сколько">
            <input v-model="woNote" placeholder="испортилось…" style="flex: 1; min-width: 100px"></div>
          <div><button class="sm danger" :disabled="busy || !woQty" @click="writeOff">Списать</button></div>
        </div>
      </div>

      <div class="row">
        <button class="sm" :disabled="busy" @click="flags({ is_staple: !it.is_staple }, it.is_staple ? 'Снова учитываем остаток' : 'Теперь базовый')">{{ it.is_staple ? 'Учитывать остаток' : 'Сделать базовым' }}</button>
        <button v-if="it.is_staple" class="sm" :disabled="busy" @click="flags({ is_low: !it.is_low }, it.is_low ? 'Отметка снята' : 'Добавится в покупки')">{{ it.is_low ? 'Хватает' : 'Заканчивается' }}</button>
        <span class="tiny muted">Базовые (соль, масло, специи) не считаются по граммам — в покупки попадают по отметке «заканчивается».</span>
      </div>

      <details v-if="history.length">
        <summary class="small muted" style="cursor: pointer">История ({{ history.length }})</summary>
        <div class="stack tight" style="margin-top: 8px">
          <div v-for="m in history" :key="m.id" class="row between small">
            <span>{{ fmtDateTime(m.created_at) }} · {{ REASON[m.reason] || m.reason }}<span v-if="m.note" class="muted"> · {{ m.note }}</span></span>
            <b class="num" :style="{ color: n(m.delta) < 0 ? 'var(--danger)' : 'var(--accent)' }">{{ n(m.delta) > 0 ? '+' : '' }}{{ fmtQty(m.delta, it.unit) }}</b>
          </div>
        </div>
      </details>
    </Modal>`,
};

// Быстрая инвентаризация: по каждому товару «так и есть / нет / другое количество»
const QuickInventory = {
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

export const StockTab = {
  components: { AddLotModal, ItemModal, QuickInventory },
  setup() {
    const items = ref([]);
    const q = ref("");
    const adding = ref(false);
    const opened = ref(null);
    const quick = ref(false);
    async function load() {
      try { await ensureCatalog(); items.value = await api.get("/stock"); } catch (e) { toastError(e); }
    }
    onMounted(load);
    const list = computed(() => items.value.filter((i) => matches(i.name, q.value)));
    const groups = computed(() => {
      const map = new Map();
      for (const i of list.value) {
        const g = i.category_name || "Без категории";
        if (!map.has(g)) map.set(g, []);
        map.get(g).push(i);
      }
      return [...map.entries()].map(([name, list]) => ({ name, list }));
    });
    const checks = computed(() => items.value.filter((i) => i.needs_check).length);
    return {
      items, q, adding, opened, quick, groups, checks, load, fmtQty, fmtDayMonth, n, today: today(),
      onSaved: (list) => { if (Array.isArray(list)) items.value = list; else load(); adding.value = false; quick.value = false; },
    };
  },
  template: `
    <div class="stack">
      <div class="row">
        <input v-model="q" placeholder="Поиск…" style="max-width: 240px">
        <button class="primary sm" @click="adding = true">+ Добавить</button>
        <button class="sm" @click="quick = true" :disabled="!items.length">Инвентаризация</button>
        <span v-if="checks" class="badge warn">учёт сбился: {{ checks }}</span>
      </div>
      <div v-if="!items.length" class="card empty">Запасов пока нет. Они появятся, когда отметите покупки в списке, или добавьте вручную.</div>
      <div v-else class="card flush" style="overflow: hidden">
        <template v-for="g in groups" :key="g.name">
          <div class="shop-cat">{{ g.name }}</div>
          <div v-for="i in g.list" :key="i.item_key" class="list-item clickable" @click="opened = i">
            <div class="grow">
              <b>{{ i.name }}</b>
              <span v-if="i.is_staple" class="badge" style="margin-left: 6px">базовый</span>
              <span v-if="i.is_low" class="badge warn" style="margin-left: 4px">заканчивается</span>
              <span v-if="i.needs_check" class="badge warn" style="margin-left: 4px">учёт сбился</span>
              <div class="tiny muted" v-if="i.nearest_expiry">годен до {{ fmtDayMonth(i.nearest_expiry) }}<span v-if="n(i.expired) > 0" style="color: var(--danger)"> · просрочено {{ fmtQty(i.expired, i.unit) }}</span></div>
            </div>
            <b class="num nowrap" v-if="!i.is_staple">{{ fmtQty(i.remaining, i.unit) }}</b>
          </div>
        </template>
      </div>
      <AddLotModal v-if="adding" @close="adding = false" @saved="onSaved" />
      <ItemModal v-if="opened" :item="opened" @close="opened = null" @saved="onSaved" />
      <QuickInventory v-if="quick" :items="items" @close="quick = false" @saved="onSaved" />
    </div>`,
};
