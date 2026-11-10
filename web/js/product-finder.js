// Поиск продукта: свой справочник → штрихкод (камера или цифры) → Open Food Facts.
// Найденное в Open Food Facts становится «черновиком»: пользователь проверяет
// цифры с упаковки, и продукт сохраняется в справочник (saveDraft).
import { ref, reactive, computed, watch, nextTick, onMounted, onBeforeUnmount } from "../vendor/vue.esm-browser.prod.js";
import { api } from "./api.js";
import { BarcodeScanner, KbjuInputs, Macros } from "./components.js";
import { state, activeVariants, variantIndex, loadProducts } from "./store.js";
import { bjuLine, fmt, fmtQty, fuzzyScore, grams, local, n } from "./util.js";

const CODE_RE = /^\d{8,14}$/;
const LAST_CATEGORY = "ft.lastProductCategory";

// Вторая строка подсказки OFF: бренд · производитель · упаковка (или «100 г»)
export function offSub(s) {
  const pkg = s.package_amount ? fmtQty(s.package_amount, s.package_unit || "g") : "100 г";
  return [s.brand, s.manufacturer, pkg].filter(Boolean).join(" · ");
}
const hasBju = (s) => s.proteins != null || s.fats != null || s.carbs != null;
const offKcal = (s) => (s.calories != null ? `${fmt(s.calories)} ккал` : hasBju(s) ? "— ккал" : "без КБЖУ");
// Б/Ж/У под калориями; у подсказки OFF без КБЖУ строки нет
const bjuOf = (m) => (m.calories == null && !hasBju(m) ? "" : bjuLine(m));

// Черновик продукта (поля формы): из подсказки Open Food Facts (source "off")
// или пустой для ручного ввода (source "manual")
export function draftFrom(s, source = "off") {
  return {
    source,
    barcode: s.barcode || null,
    // как пришло из поиска: если название поменяют — это уже другой товар, штрихкод сбросим
    searchName: source === "off" ? s.name || "" : null,
    searchBarcode: source === "off" ? s.barcode || null : null,
    name: s.name || "",
    brand: s.brand || "",
    manufacturer: s.manufacturer || "",
    category: local.get(LAST_CATEGORY, "") || "Готовые продукты",
    kbju: { calories: s.calories ?? "", proteins: s.proteins ?? "", fats: s.fats ?? "", carbs: s.carbs ?? "" },
    package_amount: s.package_amount ? n(s.package_amount) : null,
    package_unit: s.package_unit || "g",
  };
}

const KBJU_KEYS = ["calories", "proteins", "fats", "carbs"];
const kbjuEmpty = (k) => KBJU_KEYS.every((key) => k[key] === "" || k[key] == null);

// kbjuOptional — КБЖУ можно не вносить вовсе (покупки, чек): продукт сохранится «без КБЖУ»,
// цифры спросим при первом использовании в плане или рецепте
export function draftError(d, { kbjuOptional = false } = {}) {
  if (!d.name.trim() || !d.category.trim()) return "Укажите название и категорию";
  if (kbjuOptional && kbjuEmpty(d.kbju)) return "";
  if (KBJU_KEYS.some((k) => d.kbju[k] === "" || d.kbju[k] == null)) {
    return "Заполните КБЖУ на 100 г — с упаковки";
  }
  return "";
}

// Сохранить черновик в справочник; reuse — тот же штрихкод / название+бренд вернёт
// уже существующий (план), иначе — ошибка «уже есть» (раздел «Продукты»)
export async function saveDraft(d, { reuse = true } = {}) {
  const product = await api.post("/products/with-category", {
    category_name: d.category.trim(),
    name: d.name.trim(),
    brand_name: d.brand.trim() || "Без бренда",
    barcode: d.barcode && CODE_RE.test(d.barcode) ? d.barcode : null,
    package_amount: d.package_amount || null,
    package_unit: d.package_amount ? d.package_unit : null,
    reuse_existing: reuse,
    // КБЖУ не внесены — продукт сохраняется «на потом» (kbju_missing)
    base_variant: kbjuEmpty(d.kbju) ? null : {
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
  components: { BarcodeScanner, KbjuInputs },
  // kbjuPrompt — там, где КБЖУ нужны (план, рецепт): у продукта «без КБЖУ» спросить их сразу
  props: { modelValue: [Number, null], draft: Object, autofocus: Boolean, kbjuPrompt: Boolean },
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
      ? { name: selected.value.name, sub: selected.value.subFull, source: selected.value.active ? "" : "старая версия КБЖУ" }
      : props.draft ? {
        name: props.draft.name || "Новый продукт",
        sub: props.draft.source === "manual" ? "заполните данные ниже" : offSub(props.draft),
        source: props.draft.source === "manual" ? "вручную" : "Open Food Facts",
      } : null);
    const isCode = computed(() => CODE_RE.test(query.value.trim()));

    // Продукт завели без КБЖУ (из чека) — вносим цифры здесь: появится новая версия,
    // и выбор переключится на неё
    const fill = ref({ calories: "", proteins: "", fats: "", carbs: "" });
    const fillBusy = ref(false);
    const fillError = ref("");
    const needsKbju = computed(() => props.kbjuPrompt && !!selected.value?.kbjuMissing);
    async function saveKbju() {
      fillError.value = "";
      const k = fill.value;
      if (KBJU_KEYS.some((key) => k[key] === "" || k[key] == null)) { fillError.value = "Заполните все четыре поля — с упаковки"; return; }
      fillBusy.value = true;
      try {
        const v = await api.post(`/products/${selected.value.product.id}/variants`, {
          manufacturer_name: selected.value.manufacturer.name || null,
          calories: n(k.calories), proteins: n(k.proteins), fats: n(k.fats), carbs: n(k.carbs),
        });
        await loadProducts();
        emit("update:modelValue", v.id);
        fill.value = { calories: "", proteins: "", fats: "", carbs: "" };
      } catch (e) { fillError.value = e.message; } finally { fillBusy.value = false; }
    }

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
      enterManually, clear, root, listOpen, fill, fillBusy, fillError, needsKbju, saveKbju,
      offSub, offKcal, bjuOf, fmt,
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
      <div v-if="needsKbju" class="card stack tight">
        <div class="small"><b>У этого продукта ещё нет КБЖУ</b> <span class="muted">— его добавили из чека или покупок. Внесите цифры с упаковки, на 100 г.</span></div>
        <KbjuInputs v-model="fill" />
        <div v-if="fillError" class="small" style="color: var(--warn)">{{ fillError }}</div>
        <div class="row"><span class="grow"></span><button class="sm primary" :disabled="fillBusy" @click="saveKbju">Сохранить КБЖУ</button></div>
      </div>
      <template v-if="!chosen">
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
              <span v-if="v.kbjuMissing" class="finder-right"><span>нет КБЖУ</span></span>
              <span v-else class="finder-right"><span>{{ fmt(v.calories) }} ккал</span><span class="tiny">{{ bjuOf(v) }}</span></span>
            </div>
          </template>
          <div v-else-if="!isCode" class="picker-item muted small">В приложении не нашли</div>
          <template v-if="offRows.length">
            <div class="picker-group">Open Food Facts</div>
            <div v-for="(s, i) in offRows" :key="s.barcode || i" class="picker-item" @click="pickOff(s)">
              <span class="grow" style="min-width: 0"><span>{{ s.name }}</span>
                <span class="tiny muted ellipsis" style="display: block">{{ offSub(s) }}</span></span>
              <span class="finder-right"><span>{{ offKcal(s) }}</span><span class="tiny">{{ bjuOf(s) }}</span></span>
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
  components: { KbjuInputs, BarcodeScanner },
  // kbjuOptional — КБЖУ можно оставить пустыми (покупки): спросим при первом использовании
  props: { draft: { type: Object, required: true }, kbjuOptional: Boolean },
  setup(props) {
    const unitLabel = { g: "г", ml: "мл", pcs: "шт" };
    const scanning = ref(false);
    const barcodeReset = ref(false);
    // Выбрали товар в поиске, а потом поменяли название — штрихкод относится к тому
    // товару, а не к новому: сбрасываем
    watch(() => props.draft.name, (name) => {
      const d = props.draft;
      if (d.searchBarcode && d.barcode === d.searchBarcode && (name || "").trim() !== (d.searchName || "").trim()) {
        d.barcode = null;
        barcodeReset.value = true;
      }
    });
    watch(() => props.draft, () => { barcodeReset.value = false; });
    const onScan = (code) => { scanning.value = false; props.draft.barcode = code; props.draft.searchBarcode = null; barcodeReset.value = false; };
    return { state, unitLabel, scanning, barcodeReset, onScan };
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
      <div v-if="kbjuOptional" class="tiny muted">КБЖУ можно не заполнять сейчас — спросим, когда добавите продукт в план или рецепт.</div>
      <div class="row small">
        <span class="muted">Упаковка</span>
        <input type="number" min="0" step="any" v-model.number="draft.package_amount" placeholder="—" style="width: 90px">
        <select v-model="draft.package_unit" style="width: 70px">
          <option value="g">г</option><option value="ml">мл</option><option value="pcs">шт</option>
        </select>
      </div>
      <div class="field"><span>Штрихкод (необязательно)</span>
        <div class="row" style="flex-wrap: nowrap">
          <input v-model="draft.barcode" inputmode="numeric" placeholder="4600000000000" @input="draft.searchBarcode = null; barcodeReset = false">
          <button class="sm" @click="scanning = true" title="Сканировать штрихкод камерой" aria-label="Сканировать штрихкод">📷</button>
        </div>
        <span v-if="barcodeReset" class="tiny muted">Название изменено — штрихкод найденного товара сброшен.</span>
      </div>
      <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onScan" />
    </div>`,
};


// ---------- Состав блюда: [{ variant_id, weight_g, draft? }] + итоговый вес/КБЖУ ----------
// Каждый ингредиент ищется тем же поиском, что продукты в плане. Найденное в Open Food
// Facts или введённое вручную — «черновик» строки; в справочник он попадает при
// сохранении (рецепта, готовки, состава кастрюли) через resolveDraftIngredients.
let rowSeq = 0;
export const IngredientsEditor = {
  components: { ProductFinder, OffDraftCard, Macros },
  // exactToggle — показывать «🎯 именно этот вариант» (в шаблоне рецепта; в готовке не нужен)
  props: { modelValue: { type: Array, required: true }, cookedWeight: [Number, String], exactToggle: Boolean },
  emits: ["update:modelValue"],
  setup(props, { emit }) {
    // стабильный ключ строки: иначе при вводе веса строка пересоздаётся и теряет фокус
    watch(() => props.modelValue, (rows) => { for (const r of rows) if (!r._k) r._k = ++rowSeq; }, { immediate: true, deep: false });
    // Открыт для правки один ингредиент (аккордеон): остальные — компактной строкой.
    // Сразу открыт первый незаполненный (новый рецепт начинается с пустой строки).
    const openKey = ref(props.modelValue.find((r) => !r.variant_id && !r.draft)?._k ?? null);
    const focusKey = ref(null);
    function update(i, patch) {
      emit("update:modelValue", props.modelValue.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    }
    function add() {
      const row = { variant_id: null, weight_g: 100, draft: null, _k: ++rowSeq };
      focusKey.value = openKey.value = row._k;
      emit("update:modelValue", [...props.modelValue, row]);
    }
    function remove(i) {
      if (props.modelValue[i]._k === openKey.value) openKey.value = null;
      emit("update:modelValue", props.modelValue.filter((_, j) => j !== i));
    }
    const open = (r) => { openKey.value = r._k; };
    const close = () => { openKey.value = null; };
    // компактная строка: что выбрано и с какой подписью
    function title(r) {
      if (r.draft) return { name: r.draft.name || "Новый продукт", sub: r.draft.source === "manual" ? "новый, заполните данные" : "из Open Food Facts" };
      const v = variantIndex.value[r.variant_id];
      if (!v) return { name: "Продукт не выбран", sub: "", empty: true };
      return { name: v.name, sub: [v.sub, v.active ? "" : "старая версия КБЖУ", v.kbjuMissing ? "нет КБЖУ — нажмите «Изменить»" : ""].filter(Boolean).join(" · ") };
    }
    function per100Of(r) {
      if (r.draft) {
        const k = r.draft.kbju;
        return { calories: n(k.calories), proteins: n(k.proteins), fats: n(k.fats), carbs: n(k.carbs) };
      }
      return variantIndex.value[r.variant_id] || null;
    }
    const totals = computed(() => {
      const t = { raw: 0, calories: 0, proteins: 0, fats: 0, carbs: 0 };
      for (const r of props.modelValue) {
        const w = n(r.weight_g);
        t.raw += w;
        const v = per100Of(r);
        if (!v) continue;
        for (const key of ["calories", "proteins", "fats", "carbs"]) t[key] += (n(v[key]) * w) / 100;
      }
      return t;
    });
    const per100 = computed(() => {
      const cw = n(props.cookedWeight);
      if (!cw) return null;
      const k = 100 / cw;
      const t = totals.value;
      return { calories: t.calories * k, proteins: t.proteins * k, fats: t.fats * k, carbs: t.carbs * k };
    });
    return { update, add, remove, open, close, title, totals, per100, grams, fmt, n, focusKey, openKey };
  },
  template: `
    <div class="stack tight">
      <div v-for="(r, i) in modelValue" :key="r._k" class="ingr" :class="{ open: r._k === openKey }">
        <div v-if="r._k !== openKey" class="ingr-line" @click="open(r)">
          <span class="grow" style="min-width: 0">
            <span :class="{ muted: title(r).empty }">{{ title(r).name }}</span>
            <span v-if="r.exact" title="Покупать именно этот бренд"> 🎯</span>
            <span v-if="title(r).sub" class="tiny muted ellipsis" style="display: block">{{ title(r).sub }}</span>
          </span>
          <b class="num nowrap">{{ fmt(r.weight_g, n(r.weight_g) % 1 ? 1 : 0) }} г</b>
          <button class="sm" @click.stop="open(r)">Изменить</button>
          <button class="ghost icon" @click.stop="remove(i)" title="Убрать ингредиент" aria-label="Убрать ингредиент">✕</button>
        </div>
        <div v-else class="stack tight">
          <div class="ingr-row">
            <div class="ingr-find">
              <ProductFinder :modelValue="r.variant_id" :draft="r.draft" :autofocus="r._k === focusKey" kbjuPrompt
                @update:modelValue="update(i, { variant_id: $event })" @update:draft="update(i, { draft: $event })" />
            </div>
            <div class="ingr-qty">
              <input type="number" min="0.1" step="any" :value="r.weight_g"
                     @input="update(i, { weight_g: $event.target.value })" aria-label="Вес, г">
              <span class="muted small">г</span>
              <button v-if="exactToggle" type="button" class="sm" :class="r.exact ? 'primary' : 'ghost'" style="padding: 2px 6px"
                      :title="r.exact ? 'Покупать именно этот бренд' : 'Подойдёт любой бренд этого товара — нажмите, если важен именно этот'"
                      @click="update(i, { exact: !r.exact })">🎯</button>
              <button class="ghost icon" @click="remove(i)" title="Убрать ингредиент" aria-label="Убрать ингредиент">✕</button>
            </div>
          </div>
          <OffDraftCard v-if="r.draft" :draft="r.draft" />
          <div class="row"><span class="grow"></span><button class="sm primary" @click="close">Готово</button></div>
        </div>
      </div>
      <button type="button" class="ingr-add" @click="add">+ Добавить ингредиент</button>
      <div class="row between small">
        <span class="muted">{{ modelValue.length }} ингр.</span>
        <span class="muted">Сырой вес: <b class="num">{{ grams(totals.raw) }}</b></span>
      </div>
      <div class="small" v-if="per100"><span class="muted">На 100 г готового: </span><Macros :m="per100" :digits="1" /></div>
    </div>`,
};

// Перед сохранением состава: черновики ингредиентов (из Open Food Facts или ручные) —
// в справочник, строкам — их variant_id. Ошибка в черновике — с названием ингредиента.
export async function resolveDraftIngredients(rows) {
  for (const r of rows) {
    const v = r.variant_id && variantIndex.value[r.variant_id];
    if (v?.kbjuMissing) throw new Error(`Ингредиент «${v.name}»: у продукта нет КБЖУ — откройте его («Изменить») и внесите цифры`);
  }
  for (const r of rows) {
    if (!r.draft || r.variant_id) continue;
    const err = draftError(r.draft);
    if (err) throw new Error(`Ингредиент «${r.draft.name || "без названия"}»: ${err}`);
  }
  for (const r of rows) {
    if (!r.draft || r.variant_id) continue;
    const product = await saveDraft(r.draft);
    const id = activeVariantOf(product, r.draft.manufacturer || r.draft.brand);
    if (!id) throw new Error(`У продукта «${product.name}» нет активной версии КБЖУ`);
    r.variant_id = id;
    r.draft = null;
  }
  return rows;
}
