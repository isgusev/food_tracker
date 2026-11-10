// Общий список покупок семьи: формируется из плана за вычетом запасов,
// «куплено» сразу кладёт товар в запасы; второй телефон видит отметки.
import { ref, computed, watch, onMounted, onBeforeUnmount } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal } from "../components.js";
import { ReceiptModal } from "../receipts.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError } from "../product-finder.js";
import { state, ensureCatalog, variantIndex, toast, toastError } from "../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, local, n, startOfWeek, today, UNIT_LABEL } from "../util.js";

const POLL_MS = 15000;

function pkgText(l) {
  if (l.package_amount && l.package_count) {
    const one = fmtQty(l.package_amount, l.unit);
    return l.package_count === 1 && l.unit === "pcs" && n(l.package_amount) === 1 ? fmtQty(l.package_count, "pcs") : `${l.package_count} × ${one}`;
  }
  return l.needed ? fmtQty(l.needed, l.unit) : "";
}

// Внеплановая покупка: тот же поиск, что в плане (справочник → штрихкод/📷 → Open Food Facts →
// вручную), количество — упаковками или вручную. КБЖУ у нового продукта можно не вносить.
const ExtraModal = {
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

// У товара нет упаковки — округлять покупку не до чего: спросим, сколько в пачке
const PackageModal = {
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

// Позиция после «куплено»: количество, цена, срок
const BoughtModal = {
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

export const ShoppingView = {
  components: { BoughtModal, ReceiptModal, PackageModal, ExtraModal },
  props: { query: Object },
  setup(props) {
    const lst = ref(null);
    const loading = ref(false);
    // Оценка суммы — по последней цене товара из прошлых покупок
    const prices = ref({});
    api.get("/finance/prices").then((r) => { prices.value = Object.fromEntries(r.map((p) => [p.item_key, n(p.unit_price)])); }).catch(() => {});
    const lineQty = (l) => (l.package_amount && l.package_count ? n(l.package_amount) * l.package_count : n(l.needed));
    const estimate = (l) => (prices.value[l.item_key] != null && lineQty(l) > 0 ? prices.value[l.item_key] * lineQty(l) : null);
    const estTotal = computed(() => {
      let sum = 0, unknown = 0;
      for (const l of lst.value?.lines || []) {
        if (l.is_checked) continue;
        const e = estimate(l);
        if (e == null) unknown++; else sum += e;
      }
      return { sum, unknown };
    });
    const start = ref(props.query?.start || today());
    const end = ref(props.query?.end || addDays(startOfWeek(today()), 6));
    const editing = ref(null);
    const extraOpen = ref(false);
    let timer = null;

    async function refresh(silent = true) {
      await flushQueue();
      try {
        const res = await api.get("/shopping-lists/active");
        lst.value = res;
        if (res && !props.query?.start) { start.value = res.start_date; end.value = res.end_date; }
      } catch (e) { if (!silent) toastError(e); }
    }
    async function generate() {
      if (end.value < start.value) { toast("Дата окончания раньше даты начала", "error"); return; }
      loading.value = true;
      try {
        lst.value = await api.post("/shopping-lists", { start_date: start.value, end_date: end.value });
        toast("Список обновлён по плану и запасам");
      } catch (e) { toastError(e); } finally { loading.value = false; }
    }
    const onVisible = () => { if (!document.hidden) { refresh(); loadReceiptsReady(); } };
    onMounted(async () => {
      await refresh(false);
      // Пришли из плана с конкретным периодом — сразу формируем
      if (props.query?.start && (!lst.value || lst.value.start_date !== start.value || lst.value.end_date !== end.value)) await generate();
      timer = setInterval(() => { if (!document.hidden && !editing.value) refresh(); }, POLL_MS);
      document.addEventListener("visibilitychange", onVisible);
      ensureCatalog().catch(() => {});
    });
    onBeforeUnmount(() => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onOnline);
    });

    const groups = computed(() => {
      const map = new Map();
      for (const l of lst.value?.lines || []) {
        if (l.is_checked) continue;
        const g = l.category_name || "Без категории";
        if (!map.has(g)) map.set(g, []);
        map.get(g).push(l);
      }
      return [...map.entries()].map(([name, list]) => ({ name, list }));
    });
    const bought = computed(() => (lst.value?.lines || []).filter((l) => l.is_checked));
    const spent = computed(() => bought.value.reduce((s, l) => s + n(l.price), 0));

    async function act(fn) {
      try { lst.value = await fn(); } catch (e) { toastError(e); }
    }

    // Офлайн-очередь отметок: в магазине без сети отметка ставится сразу,
    // а на сервер уходит, когда связь вернётся
    const QKEY = "ft.shopQueue";
    const queue = ref(local.get(QKEY, []));
    const saveQueue = () => local.set(QKEY, queue.value);
    async function toggle(l, kind) {
      try {
        lst.value = await api.post(`/shopping-lists/lines/${l.id}/${kind}`, {});
      } catch (e) {
        if (e.status !== 0) { toastError(e); return; }
        queue.value = queue.value.filter((q) => q.id !== l.id).concat({ id: l.id, kind });
        saveQueue();
        l.is_checked = kind === "check";
        toast("Нет сети — отметка отправится, когда связь вернётся");
      }
    }
    async function flushQueue() {
      if (!queue.value.length) return;
      const rest = [];
      for (const q of queue.value) {
        try { await api.post(`/shopping-lists/lines/${q.id}/${q.kind}`, {}); }
        catch (e) { if (e.status === 0) rest.push(q); /* иначе уже применено/неактуально */ }
      }
      queue.value = rest;
      saveQueue();
      if (!rest.length) toast("Отметки, сделанные без сети, отправлены");
    }
    const onOnline = () => flushQueue().then(() => refresh());
    window.addEventListener("online", onOnline);
    const check = (l) => toggle(l, "check");
    const uncheck = (l) => toggle(l, "uncheck");
    const remove = (l) => act(() => api.del(`/shopping-lists/lines/${l.id}`));
    function onExtraSaved(res) { lst.value = res; extraOpen.value = false; toast("Добавлено в список"); }
    async function close() {
      const unpriced = bought.value.filter((l) => l.price == null).length;
      if (!confirm(`Закрыть список?${unpriced ? `\nУ ${unpriced} покупок не указана цена — её можно будет дописать в запасах.` : ""}`)) return;
      try { await api.post(`/shopping-lists/${lst.value.id}/close`); lst.value = null; toast("Список закрыт"); }
      catch (e) { toastError(e); }
    }
    function preset(kind) {
      const t = today(), w = startOfWeek(t);
      if (kind === "rest") { start.value = t; end.value = addDays(w, 6); }
      if (kind === "next") { start.value = addDays(w, 7); end.value = addDays(w, 13); }
      if (kind === "3d") { start.value = t; end.value = addDays(t, 2); }
    }
    const asText = () => groups.value.map((g) => `${g.name}:\n` + g.list.map((l) => `☐ ${l.product_name} — ${pkgText(l)}`).join("\n")).join("\n\n");
    async function copy() {
      try { await navigator.clipboard.writeText(asText()); toast("Список скопирован"); }
      catch { toast("Не удалось скопировать", "error"); }
    }

    // Упаковка добавлена — пересчитываем список за тот же период (отмеченное сохранится)
    const packaging = ref(null);
    async function onPackageSaved() {
      packaging.value = null;
      try {
        lst.value = await api.post("/shopping-lists", { start_date: lst.value.start_date, end_date: lst.value.end_date });
        toast("Упаковка сохранена — список пересчитан");
      } catch (e) { toastError(e); }
    }
    const needsPackage = (l) => !l.package_amount && !l.is_staple && l.unit !== "pcs";
    const receiptOpen = ref(false);
    // Чеки, которые расшифровались, но ещё не разобраны («готов к проверке»)
    const receiptsReady = ref(0);
    async function loadReceiptsReady() {
      try { receiptsReady.value = (await api.get("/receipts")).filter((r) => r.status === "done").length; }
      catch { receiptsReady.value = 0; }
    }
    onMounted(loadReceiptsReady);
    function onReceiptApplied() { receiptOpen.value = false; refresh(); loadReceiptsReady(); }
    function onReceiptClosed() { receiptOpen.value = false; loadReceiptsReady(); }
    return {
      receiptOpen, onReceiptApplied, onReceiptClosed, receiptsReady, packaging, onPackageSaved, needsPackage,
      lst, loading, start, end, editing, estimate, estTotal, queue, extraOpen, onExtraSaved, groups, bought, spent,
      generate, check, uncheck, remove, close, preset, copy, pkgText, fmt, fmtQty, fmtDayMonth, n,
      onSaved: (res) => { lst.value = res; editing.value = null; },
    };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Покупки</h1>
        <div class="row">
          <button @click="receiptOpen = true" title="Загрузить покупки и цены из чека по QR-коду"
                  :class="{ primary: receiptsReady }">🧾 Чек<template v-if="receiptsReady"> · готов{{ receiptsReady > 1 ? ' ' + receiptsReady : '' }}</template></button>
          <template v-if="lst">
          <button @click="copy">📋 Копировать</button>
          <button @click="close">Закрыть список</button>
          </template>
        </div>
      </div>

      <div class="card stack" style="margin-bottom: 14px">
        <div class="row">
          <label class="field" style="width: 170px"><span>С</span><input type="date" v-model="start"></label>
          <label class="field" style="width: 170px"><span>По</span><input type="date" v-model="end"></label>
          <button class="primary" style="align-self: flex-end" :disabled="loading" @click="generate">{{ lst ? 'Пересчитать' : 'Сформировать список' }}</button>
        </div>
        <div class="row tight">
          <button class="sm" @click="preset('rest')">До конца недели</button>
          <button class="sm" @click="preset('next')">Следующая неделя</button>
          <button class="sm" @click="preset('3d')">3 дня</button>
        </div>
        <div class="tiny muted">
          Считается из плана: несъеденные порции блюд, которых нет в холодильнике, минус то, что уже есть в запасах.
          Список общий для семьи — отметки «куплено» видны на всех телефонах, а товар сразу попадает в «Холодильник → Продукты».
        </div>
      </div>

      <div v-if="!lst" class="card empty">Активного списка нет. Выберите период и нажмите «Сформировать список».</div>
      <template v-else>
        <div class="row between small muted" style="margin-bottom: 8px">
          <span><span v-if="queue.length" class="badge warn" style="margin-right: 6px">не отправлено: {{ queue.length }}</span>{{ fmtDayMonth(lst.start_date) }} — {{ fmtDayMonth(lst.end_date) }} · осталось {{ lst.lines.length - bought.length }}, куплено {{ bought.length }}
            <template v-if="estTotal.sum"> · ≈ {{ fmt(estTotal.sum) }} ₽<template v-if="estTotal.unknown"> + {{ estTotal.unknown }} без цены</template></template></span>
          <button class="sm" @click="extraOpen = true">+ Внеплановая покупка</button>
        </div>
        <ExtraModal v-if="extraOpen" :listId="lst.id" @close="extraOpen = false" @saved="onExtraSaved" />

        <div v-if="!groups.length && !bought.length" class="card empty">Покупать нечего — всё есть дома или план пуст.</div>
        <div v-if="groups.length" class="card flush" style="overflow: hidden">
          <template v-for="g in groups" :key="g.name">
            <div class="shop-cat">{{ g.name }}</div>
            <div v-for="l in g.list" :key="l.id" class="shop-item">
              <input type="checkbox" @change="check(l)" :aria-label="'Купил: ' + l.product_name">
              <span class="grow shop-name">{{ l.product_name }}
                <span v-if="l.is_staple" class="badge warn">заканчивается</span>
                <span v-if="l.is_extra" class="badge">вне плана</span>
                <span v-if="l.is_exact" class="badge warn" title="Нужен именно этот бренд">🎯 {{ l.brand }}</span>
                <span v-else-if="l.brand" class="tiny muted" style="display: block">{{ l.is_extra ? l.brand : 'обычно ' + l.brand }}</span></span>
              <span class="nowrap" style="text-align: right"><b class="num">{{ pkgText(l) }}</b>
                <div v-if="estimate(l) != null" class="tiny muted num">≈ {{ fmt(estimate(l)) }} ₽</div>
                <button v-if="needsPackage(l)" class="sm ghost" style="padding: 0 4px; display: block; margin-left: auto" @click="packaging = l"
                        title="У товара нет упаковки — укажите, и покупка округлится до целых пачек">📦 пачка?</button></span>
              <button class="ghost icon sm" @click="remove(l)" title="Убрать из списка">✕</button>
            </div>
          </template>
        </div>

        <template v-if="bought.length">
          <div class="row between small muted" style="margin: 16px 0 8px">
            <span>Куплено — уже в запасах</span>
            <span v-if="spent">потрачено {{ fmt(spent, 2) }} ₽</span>
          </div>
          <div class="card flush" style="overflow: hidden">
            <div v-for="l in bought" :key="l.id" class="shop-item done">
              <input type="checkbox" checked @change="uncheck(l)" :aria-label="'Не купил: ' + l.product_name">
              <span class="grow shop-name">{{ l.product_name }}</span>
              <span class="small muted num nowrap">{{ fmtQty(l.bought_quantity, l.unit) }}<template v-if="l.price != null"> · {{ fmt(l.price, 2) }} ₽</template><template v-if="l.expires_on"> · до {{ fmtDayMonth(l.expires_on) }}</template></span>
              <button class="sm" @click="editing = l">{{ l.price == null ? 'Цена…' : 'Изменить' }}</button>
            </div>
          </div>
        </template>
      </template>

      <BoughtModal v-if="editing" :line="editing" @close="editing = null" @saved="onSaved" />
      <PackageModal v-if="packaging" :line="packaging" @close="packaging = null" @saved="onPackageSaved" />
      <ReceiptModal v-if="receiptOpen" @close="onReceiptClosed" @applied="onReceiptApplied" />
    </div>`,
};
