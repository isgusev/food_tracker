// Поиск продукта: свой справочник → штрихкод (камера или цифры) → Open Food Facts.
// Найденное в Open Food Facts становится «черновиком»: пользователь проверяет
// цифры с упаковки, и продукт сохраняется в справочник (saveDraft).
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from "../vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { Modal, BarcodeScanner, KbjuInputs } from "./components.js";
import { state, activeVariants, variantIndex, loadProducts } from "./store.js";
import { fmt, fmtQty, fuzzyScore, local, n } from "./util.js";

const CODE_RE = /^\d{8,14}$/;
const LAST_CATEGORY = "ft.lastProductCategory";

// Вторая строка подсказки OFF: бренд · производитель · упаковка (или «100 г»)
export function offSub(s) {
  const pkg = s.package_amount ? fmtQty(s.package_amount, s.package_unit || "g") : "100 г";
  return [s.brand, s.manufacturer, pkg].filter(Boolean).join(" · ");
}
const offKcal = (s) => (s.calories != null ? `${fmt(s.calories)} ккал` : "без КБЖУ");

// Черновик продукта (поля формы): из подсказки Open Food Facts (source "off")
// или пустой для ручного ввода (source "manual")
export function draftFrom(s, source = "off") {
  return {
    source,
    barcode: s.barcode || null,
    name: s.name || "",
    brand: s.brand || "",
    manufacturer: s.manufacturer || "",
    category: local.get(LAST_CATEGORY, "") || "Готовые продукты",
    kbju: { calories: s.calories ?? "", proteins: s.proteins ?? "", fats: s.fats ?? "", carbs: s.carbs ?? "" },
    package_amount: s.package_amount ? n(s.package_amount) : null,
    package_unit: s.package_unit || "g",
  };
}

export function draftError(d) {
  if (!d.name.trim() || !d.category.trim()) return "Укажите название и категорию";
  if (["calories", "proteins", "fats", "carbs"].some((k) => d.kbju[k] === "" || d.kbju[k] == null)) {
    return "Заполните КБЖУ на 100 г — с упаковки";
  }
  return "";
}

// Сохранить черновик в справочник; тот же штрихкод / название+бренд — вернётся уже существующий
export async function saveDraft(d) {
  const product = await api.post("/products/with-category", {
    category_name: d.category.trim(),
    name: d.name.trim(),
    brand_name: d.brand.trim() || "Без бренда",
    barcode: d.barcode && CODE_RE.test(d.barcode) ? d.barcode : null,
    package_amount: d.package_amount || null,
    package_unit: d.package_amount ? d.package_unit : null,
    reuse_existing: true,
    base_variant: {
      manufacturer_name: d.manufacturer.trim() || d.brand.trim() || null,
      calories: n(d.kbju.calories), proteins: n(d.kbju.proteins), fats: n(d.kbju.fats), carbs: n(d.kbju.carbs),
    },
  });
  local.set(LAST_CATEGORY, d.category.trim());
  await loadProducts();
  return product;
}

// Активная версия КБЖУ продукта (для плана): производитель с этикетки, иначе первый
export function activeVariantOf(product, makerName) {
  const p = state.products.find((x) => x.id === product.id) || product;
  const want = (makerName || "").trim().toLowerCase();
  const makers = [...(p.manufacturers || [])].sort((a, b) =>
    Number((b.name || "").toLowerCase() === want) - Number((a.name || "").toLowerCase() === want));
  for (const m of makers) {
    const v = (m.variants || []).find((x) => x.is_active);
    if (v) return v.id;
  }
  return null;
}

// Запрос в Open Food Facts по названию (общий для плана и справочника)
function useOffSearch() {
  const off = reactive({ q: "", loading: false, items: [], local: [], done: false, error: "" });
  let seq = 0;
  function reset() { seq++; Object.assign(off, { q: "", loading: false, items: [], local: [], done: false, error: "" }); }
  async function search(q) {
    q = q.trim();
    if (q.length < 2) return;
    const my = ++seq;
    Object.assign(off, { q, loading: true, error: "", done: false });
    try {
      const r = await api.get("/products/off-search", { q });
      if (my !== seq) return;
      off.items = r.items;
      off.local = r.local;
      off.error = r.available ? "" : "Open Food Facts сейчас не отвечает — попробуйте позже или заполните вручную.";
    } catch (e) {
      if (my === seq) off.error = e.message;
    } finally {
      if (my === seq) { off.loading = false; off.done = true; }
    }
  }
  return { off, search, reset };
}

// ---------- Поиск продукта для плана ----------
// v-model — variant_id своего продукта; v-model:draft — черновик из Open Food Facts
export const ProductFinder = {
  components: { BarcodeScanner },
  props: { modelValue: [Number, null], draft: Object, autofocus: Boolean },
  emits: ["update:modelValue", "update:draft"],
  setup(props, { emit }) {
    const query = ref("");
    const input = ref(null);
    // Список результатов — не форма: клик вне поиска его прячет (текст остаётся),
    // фокус в поле или ввод — показывает снова
    const root = ref(null);
    const listOpen = ref(true);
    const onOutside = (e) => { if (root.value && !root.value.contains(e.target)) listOpen.value = false; };
    onMounted(() => document.addEventListener("pointerdown", onOutside));
    onBeforeUnmount(() => document.removeEventListener("pointerdown", onOutside));
    const scanning = ref(false);
    const hint = ref("");
    const codeHit = ref(null);   // подсказка OFF, найденная по штрихкоду
    const { off, search, reset } = useOffSearch();

    const selected = computed(() => (props.modelValue ? variantIndex.value[props.modelValue] : null));
    const chosen = computed(() => selected.value
      ? { name: selected.value.name, sub: selected.value.subFull, source: "" }
      : props.draft ? {
        name: props.draft.name || "Новый продукт",
        sub: props.draft.source === "manual" ? "заполните данные ниже" : offSub(props.draft),
        source: props.draft.source === "manual" ? "вручную" : "Open Food Facts",
      } : null);
    const isCode = computed(() => CODE_RE.test(query.value.trim()));

    const localRows = computed(() => {
      const q = query.value.trim();
      if (!q) return [];
      // нечётко: начало слова и опечатки тоже находятся, самые похожие — первыми
      const rows = isCode.value
        ? activeVariants.value.filter((v) => v.product.barcode === q)
        : activeVariants.value
          .map((v) => ({ v, s: fuzzyScore(q, `${v.name} ${v.subFull}`) }))
          .filter((x) => x.s >= 0.6)
          .sort((a, b) => b.s - a.s)
          .slice(0, 30)
          .map((x) => x.v);
      // продукты, которые OFF нашёл по названию, а у нас они уже есть (по штрихкоду)
      for (const p of off.local) {
        const id = activeVariantOf(p);
        if (id && !rows.some((r) => r.id === id) && variantIndex.value[id]) rows.push(variantIndex.value[id]);
      }
      return rows;
    });

    let timer = null;
    watch(query, (q) => {
      listOpen.value = true;
      clearTimeout(timer);
      reset(); hint.value = ""; codeHit.value = null;
      q = q.trim();
      if (CODE_RE.test(q)) timer = setTimeout(() => lookupCode(q), 250);
      // в справочнике ничего — сами переключаемся на Open Food Facts
      else if (q.length >= 3) timer = setTimeout(() => { if (!localRows.value.length) search(q); }, 900);
    });

    async function lookupCode(code) {
      if (localRows.value.length) return;
      hint.value = "Ищем по штрихкоду…";
      try {
        const r = await api.get(`/products/barcode/${code}`);
        if (query.value.trim() !== code) return;
        if (r.source === "local") {
          if (!state.products.some((p) => p.id === r.product.id)) await loadProducts();
          const id = activeVariantOf(r.product);
          hint.value = "";
          if (id) pickLocal(variantIndex.value[id]);
        } else if (r.source === "openfoodfacts") {
          codeHit.value = { ...r.suggestion, barcode: code };
          hint.value = "";
        } else {
          hint.value = "По штрихкоду не нашли ни у нас, ни в Open Food Facts — попробуйте по названию.";
        }
      } catch (e) { hint.value = e.message; }
    }
    function onScan(code) { scanning.value = false; query.value = code; }

    function pickLocal(v) {
      emit("update:draft", null);
      emit("update:modelValue", v.id);
      query.value = "";
    }
    function pickOff(s) {
      emit("update:modelValue", null);
      emit("update:draft", draftFrom(s));
      query.value = "";
    }
    // Не нашли (или нашли не то) — заполнить продукт вручную прямо здесь
    function enterManually() {
      const q = query.value.trim();
      emit("update:modelValue", null);
      emit("update:draft", draftFrom(CODE_RE.test(q) ? { barcode: q } : { name: q }, "manual"));
      query.value = "";
    }
    function clear() { query.value = ""; nextTick(() => input.value?.focus()); }
    function change() {
      emit("update:modelValue", null);
      emit("update:draft", null);
      nextTick(() => input.value?.focus());
    }
    const offRows = computed(() => (codeHit.value ? [codeHit.value] : off.items));
    onMounted(() => { if (props.autofocus && !chosen.value) nextTick(() => input.value?.focus()); });
    return {
      query, input, scanning, hint, off, search, chosen, isCode, localRows, offRows, onScan, pickLocal, pickOff, change,
      enterManually, clear, root, listOpen,
      offSub, offKcal, fmt,
    };
  },
  template: `
    <div class="stack tight" ref="root">
      <div v-if="chosen" class="finder-chosen">
        <span class="grow" style="min-width: 0">
          <b>{{ chosen.name }}</b> <span v-if="chosen.source" class="badge info">{{ chosen.source }}</span>
          <span class="tiny muted ellipsis" style="display: block">{{ chosen.sub }}</span>
        </span>
        <button class="sm" @click="change">Изменить</button>
      </div>
      <template v-else>
        <div class="row" style="flex-wrap: nowrap">
          <div class="clearable">
            <input ref="input" v-model="query" placeholder="Название, бренд или штрихкод…" autocomplete="off" enterkeyhint="search"
                   @focus="listOpen = true" @click="listOpen = true" @input="listOpen = true"
                   @keydown.esc.stop="listOpen = false"
                   @keydown.enter.prevent="!isCode && query.trim().length >= 2 && search(query)">
            <button v-if="query" type="button" class="clear-btn" aria-label="Очистить" title="Очистить" @click="clear">✕</button>
          </div>
          <button class="sm" @click="scanning = true" title="Сканировать штрихкод камерой" aria-label="Сканировать штрихкод">📷</button>
        </div>
        <div v-if="query.trim() && listOpen" class="row between small" style="flex-wrap: nowrap">
          <span class="muted">{{ off.loading ? 'Ищем в Open Food Facts…' : 'Нет нужного?' }}</span>
          <button class="sm ghost finder-manual" @click="enterManually">✏️ {{ isCode ? 'Ввести со штрихкодом' : 'Ввести вручную' }}</button>
        </div>
        <div v-if="query.trim() && listOpen" class="finder-list">
          <template v-if="localRows.length">
            <div class="picker-group">В приложении</div>
            <div v-for="v in localRows" :key="v.id" class="picker-item" @click="pickLocal(v)">
              <span class="grow" style="min-width: 0"><span>{{ v.name }}</span>
                <span class="tiny muted ellipsis" style="display: block">{{ v.subFull }}</span></span>
              <span class="muted small nowrap num">{{ fmt(v.calories) }} ккал</span>
            </div>
          </template>
          <div v-else-if="!isCode" class="picker-item muted small">В приложении не нашли</div>
          <template v-if="offRows.length">
            <div class="picker-group">Open Food Facts</div>
            <div v-for="(s, i) in offRows" :key="s.barcode || i" class="picker-item" @click="pickOff(s)">
              <span class="grow" style="min-width: 0"><span>{{ s.name }}</span>
                <span class="tiny muted ellipsis" style="display: block">{{ offSub(s) }}</span></span>
              <span class="muted small nowrap num">{{ offKcal(s) }}</span>
            </div>
          </template>
          <div v-if="hint" class="picker-item muted small">{{ hint }}</div>
          <div v-else-if="off.error" class="picker-item small" style="color: var(--warn)">{{ off.error }}</div>
          <div v-else-if="off.done && !offRows.length" class="picker-item muted small">В Open Food Facts тоже не нашли — введите вручную.</div>
          <div v-if="!isCode && !off.done && !off.loading && localRows.length && query.trim().length >= 2" class="picker-item">
            <button class="sm ghost" @click="search(query)">Нет нужного? Искать в Open Food Facts</button>
          </div>
        </div>
      </template>
      <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onScan" />
    </div>`,
};

// ---------- Черновик из Open Food Facts: проверить и дополнить перед сохранением ----------
export const OffDraftCard = {
  components: { KbjuInputs },
  props: { draft: { type: Object, required: true } },
  setup() {
    const unitLabel = { g: "г", ml: "мл", pcs: "шт" };
    return { state, unitLabel };
  },
  template: `
    <div class="card stack tight">
      <div class="tiny muted" v-if="draft.source === 'manual'">Новый продукт: заполните название, категорию и КБЖУ на 100 г с упаковки. Он сохранится в справочник.</div>
      <div class="tiny muted" v-else>Из Open Food Facts — проверьте цифры с упаковки. Продукт сохранится в справочник.</div>
      <label class="field"><span>Название</span><input v-model="draft.name" placeholder="Пита ливанская"></label>
      <div class="grid-2">
        <label class="field"><span>Бренд</span><input v-model="draft.brand" placeholder="Без бренда"></label>
        <label class="field"><span>Категория</span>
          <input v-model="draft.category" list="finder-cat-list">
          <datalist id="finder-cat-list"><option v-for="c in state.productCategories" :key="c.id" :value="c.name" /></datalist>
        </label>
      </div>
      <label class="field"><span>Производитель (если отличается от бренда)</span><input v-model="draft.manufacturer"></label>
      <KbjuInputs v-model="draft.kbju" />
      <div class="row small">
        <span class="muted">Упаковка</span>
        <input type="number" min="0" step="any" v-model.number="draft.package_amount" placeholder="—" style="width: 90px">
        <select v-model="draft.package_unit" style="width: 70px">
          <option value="g">г</option><option value="ml">мл</option><option value="pcs">шт</option>
        </select>
        <span v-if="draft.barcode" class="tiny muted">штрихкод {{ draft.barcode }}</span>
      </div>
    </div>`,
};

// ---------- Поиск по названию в Open Food Facts (для формы нового продукта) ----------
export const OffSearchModal = {
  components: { Modal },
  props: { initial: String },
  emits: ["close", "pick"],
  setup(props) {
    const q = ref(props.initial || "");
    const input = ref(null);
    const { off, search } = useOffSearch();
    onMounted(() => { nextTick(() => input.value?.focus()); if (q.value.trim().length >= 2) search(q.value); });
    return { q, input, off, search, offSub, offKcal, fmt };
  },
  template: `
    <Modal title="Поиск в Open Food Facts" dismissible @close="$emit('close')">
      <div class="row" style="flex-wrap: nowrap">
        <div class="clearable">
          <input ref="input" v-model="q" placeholder="Название и бренд: творог простоквашино" enterkeyhint="search" @keydown.enter.prevent="search(q)">
          <button v-if="q" type="button" class="clear-btn" aria-label="Очистить" title="Очистить" @click="q = ''; input.focus()">✕</button>
        </div>
        <button class="primary" :disabled="q.trim().length < 2 || off.loading" @click="search(q)">Найти</button>
      </div>
      <div v-if="off.loading" class="small muted">Ищем…</div>
      <div v-else-if="off.error" class="alert warn">{{ off.error }}</div>
      <div v-if="off.local.length" class="stack tight">
        <div class="picker-group">Уже есть в справочнике</div>
        <div v-for="p in off.local" :key="p.id" class="small" style="padding: 4px 12px">{{ p.name }} <span class="muted">· {{ p.brand?.name }}</span></div>
      </div>
      <div v-if="off.items.length" class="finder-list" style="max-height: none">
        <div v-for="(s, i) in off.items" :key="s.barcode || i" class="picker-item" @click="$emit('pick', s)">
          <span class="grow" style="min-width: 0"><span>{{ s.name }}</span>
            <span class="tiny muted ellipsis" style="display: block">{{ offSub(s) }}</span></span>
          <span class="muted small nowrap num">{{ offKcal(s) }}</span>
        </div>
      </div>
      <div v-else-if="off.done && !off.error" class="small muted">Ничего не нашли — уточните запрос или заполните вручную.</div>
    </Modal>`,
};
