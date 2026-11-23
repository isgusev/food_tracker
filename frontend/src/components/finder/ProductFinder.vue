<script setup lang="ts">
// Поиск продукта: свой справочник (нечётко) → штрихкод (камера или цифры) → Open Food Facts → «ввести вручную».
// v-model — variant_id своего продукта; v-model:draft — черновик (из Open Food Facts или ручной).
// Список результатов — не форма: клик вне поиска и Esc его прячут, фокус/клик/ввод — показывают снова.
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { activeVariants, catalog, loadProducts, variantIndex, type VariantInfo } from "../../catalog";
import { CODE_RE, activeVariantOf, draftFrom, emptyKbju, kbjuIncomplete, type Draft, type Kbju, type Suggestion } from "../../drafts";
import { bjuLine, fmt, fmtQty, fuzzyScore, num } from "../../util";
import BarcodeScanner from "./BarcodeScanner.vue";
import KbjuInputs from "./KbjuInputs.vue";

// initialQuery — сразу показать результаты по этому тексту (импорт рецептов: название из файла)
const props = defineProps<{ modelValue: number | null; draft: Draft | null; autofocus?: boolean; kbjuPrompt?: boolean; initialQuery?: string }>();
const emit = defineEmits<{ "update:modelValue": [id: number | null]; "update:draft": [d: Draft | null] }>();

type Product = Schemas["ProductResponse"];

// ---- подписи
function offSub(s: Suggestion | Draft): string {
  const pkg = s.package_amount ? fmtQty(s.package_amount, s.package_unit || "g") : "100 г";
  return [s.brand, s.manufacturer, pkg].filter(Boolean).join(" · ");
}
type Macro = { calories?: unknown; proteins?: unknown; fats?: unknown; carbs?: unknown };
const hasBju = (s: Macro) => s.proteins != null || s.fats != null || s.carbs != null;
const offKcal = (s: Macro) => (s.calories != null ? `${fmt(s.calories)} ккал` : hasBju(s) ? "— ккал" : "без КБЖУ");
const bjuOf = (m: Macro) => (m.calories == null && !hasBju(m) ? "" : bjuLine(m));

// ---- состояние поиска
const query = ref(props.initialQuery ?? "");
const input = ref<HTMLInputElement | null>(null);
const root = ref<HTMLElement | null>(null);
const listOpen = ref(true);
const scanning = ref(false);
const hint = ref("");
const codeHit = ref<Suggestion | null>(null);   // подсказка OFF, найденная по штрихкоду
const off = reactive({ q: "", loading: false, items: [] as Suggestion[], local: [] as Product[], done: false, error: "" });
let seq = 0;

const onOutside = (e: PointerEvent) => { if (root.value && !root.value.contains(e.target as Node)) listOpen.value = false; };
onMounted(() => document.addEventListener("pointerdown", onOutside));
onBeforeUnmount(() => { document.removeEventListener("pointerdown", onOutside); clearTimeout(timer); });

function resetOff() { seq++; Object.assign(off, { q: "", loading: false, items: [], local: [], done: false, error: "" }); }
async function search(raw: string) {
  const q = raw.trim();
  if (q.length < 2) return;
  const my = ++seq;
  Object.assign(off, { q, loading: true, error: "", done: false });
  try {
    const r = await ok(api.GET("/api/v1/products/off-search", { params: { query: { q } } }));
    if (my !== seq) return;
    off.items = r.items ?? [];
    off.local = r.local ?? [];
    off.error = r.available ? "" : "Open Food Facts сейчас не отвечает — попробуйте позже или заполните вручную.";
  } catch (e) {
    if (my === seq) off.error = (e as Error).message;
  } finally {
    if (my === seq) { off.loading = false; off.done = true; }
  }
}

// ---- выбранное
const selected = computed<VariantInfo | null>(() => (props.modelValue ? variantIndex.value[props.modelValue] ?? null : null));
const chosen = computed(() => {
  if (selected.value) return { name: selected.value.name, sub: selected.value.subFull, source: selected.value.active ? "" : "старая версия КБЖУ" };
  const d = props.draft;
  if (!d) return null;
  return {
    name: d.name || "Новый продукт",
    sub: d.source === "manual" ? "заполните данные ниже" : offSub(d),
    source: d.source === "manual" ? "вручную" : "Open Food Facts",
  };
});
const isCode = computed(() => CODE_RE.test(query.value.trim()));

// ---- продукт без КБЖУ (заведён из чека): внести цифры — появится версия, выбор переключится на неё
const fill = ref<Kbju>(emptyKbju());
const fillBusy = ref(false);
const fillError = ref("");
const needsKbju = computed(() => !!props.kbjuPrompt && !!selected.value?.kbjuMissing);
async function saveKbju() {
  fillError.value = "";
  const s = selected.value;
  if (!s) return;
  if (kbjuIncomplete(fill.value)) { fillError.value = "Заполните все четыре поля — с упаковки"; return; }
  fillBusy.value = true;
  try {
    const k = fill.value;
    const v = await ok(api.POST("/api/v1/products/{product_id}/variants", {
      params: { path: { product_id: s.product.id } },
      body: { manufacturer_name: s.manufacturer.name || null, calories: num(k.calories), proteins: num(k.proteins), fats: num(k.fats), carbs: num(k.carbs) } as Schemas["ProductVariantCreate"],
    }));
    await loadProducts();
    emit("update:modelValue", v.id);
    fill.value = emptyKbju();
  } catch (e) { fillError.value = (e as Error).message; } finally { fillBusy.value = false; }
}

// ---- результаты
const localRows = computed<VariantInfo[]>(() => {
  const q = query.value.trim();
  if (!q) return [];
  const rows = isCode.value
    ? activeVariants.value.filter((v) => v.product.barcode === q)
    : activeVariants.value
      .map((v) => ({ v, s: fuzzyScore(q, `${v.name} ${v.subFull}`) }))
      .filter((x) => x.s >= 0.6)
      .sort((a, b) => b.s - a.s)
      .slice(0, 30)
      .map((x) => x.v);
  // продукты, которые Open Food Facts нашёл по названию, а у нас они уже есть (по штрихкоду)
  for (const p of off.local) {
    const id = activeVariantOf(p);
    if (id && !rows.some((r) => r.id === id) && variantIndex.value[id]) rows.push(variantIndex.value[id]);
  }
  return rows;
});
const offRows = computed<Suggestion[]>(() => (codeHit.value ? [codeHit.value] : off.items));

let timer: ReturnType<typeof setTimeout> | undefined;
watch(query, (raw) => {
  listOpen.value = true;
  clearTimeout(timer);
  resetOff(); hint.value = ""; codeHit.value = null;
  const q = raw.trim();
  if (CODE_RE.test(q)) timer = setTimeout(() => lookupCode(q), 250);
  // в справочнике ничего — сами переключаемся на Open Food Facts
  else if (q.length >= 3) timer = setTimeout(() => { if (!localRows.value.length) search(q); }, 900);
});

async function lookupCode(code: string) {
  if (localRows.value.length) return;
  hint.value = "Ищем по штрихкоду…";
  try {
    // код — через params.path: клиент сам его кодирует
    const r = await ok(api.GET("/api/v1/products/barcode/{code}", { params: { path: { code } } }));
    if (query.value.trim() !== code) return;
    if (r.source === "local" && r.product) {
      const product = r.product;
      if (!catalog.products.some((p) => p.id === product.id)) await loadProducts();
      const id = activeVariantOf(product);
      hint.value = "";
      if (id && variantIndex.value[id]) pickLocal(variantIndex.value[id]);
    } else if (r.source === "openfoodfacts" && r.suggestion) {
      codeHit.value = { ...r.suggestion, barcode: code };
      hint.value = "";
    } else {
      hint.value = "По штрихкоду не нашли ни у нас, ни в Open Food Facts — попробуйте по названию.";
    }
  } catch (e) { hint.value = (e as Error).message; }
}

function onScan(code: string) { scanning.value = false; query.value = code; }
function pickLocal(v: VariantInfo) { emit("update:draft", null); emit("update:modelValue", v.id); query.value = ""; }
function pickOff(s: Suggestion) { emit("update:modelValue", null); emit("update:draft", draftFrom(s)); query.value = ""; }
/** Не нашли (или нашли не то) — заполнить продукт вручную прямо здесь. */
function enterManually() {
  const q = query.value.trim();
  emit("update:modelValue", null);
  emit("update:draft", draftFrom(CODE_RE.test(q) ? { barcode: q } : { name: q }, "manual"));
  query.value = "";
}
function clear() { query.value = ""; nextTick(() => input.value?.focus()); }
function change() { emit("update:modelValue", null); emit("update:draft", null); nextTick(() => input.value?.focus()); }
function onEnter() { if (!isCode.value && query.value.trim().length >= 2) search(query.value); }
onMounted(() => {
  if (props.autofocus && !chosen.value) nextTick(() => input.value?.focus());
  // начальный текст, а в справочнике ничего — сразу ищем в Open Food Facts
  if (props.initialQuery && !chosen.value && !localRows.value.length) search(props.initialQuery);
});
</script>

<template>
  <div ref="root" class="finder">
    <div v-if="chosen" class="chosen">
      <span class="what">
        <b>{{ chosen.name }}</b> <span v-if="chosen.source" class="badge">{{ chosen.source }}</span>
        <span class="sub">{{ chosen.sub }}</span>
      </span>
      <button type="button" @click="change">Изменить</button>
    </div>

    <div v-if="needsKbju" class="nokbju">
      <p class="small"><b>У этого продукта ещё нет КБЖУ</b> <span class="muted">— его добавили из чека или покупок. Внесите цифры с упаковки, на 100 г.</span></p>
      <KbjuInputs v-model="fill" />
      <p v-if="fillError" class="small err" role="alert">{{ fillError }}</p>
      <div class="end"><button type="button" class="fill" :disabled="fillBusy" @click="saveKbju">Сохранить КБЖУ</button></div>
    </div>

    <template v-if="!chosen">
      <div class="bar">
        <div class="clearable">
          <input ref="input" v-model="query" placeholder="Название, бренд или штрихкод…" autocomplete="off" enterkeyhint="search"
                 aria-label="Поиск продукта" @focus="listOpen = true" @click="listOpen = true" @input="listOpen = true"
                 @keydown.esc.stop="listOpen = false" @keydown.enter.prevent="onEnter">
          <button v-if="query" type="button" class="x" aria-label="Очистить" @click="clear">✕</button>
        </div>
        <button type="button" class="cam" title="Сканировать штрихкод камерой" aria-label="Сканировать штрихкод" @click="scanning = true">📷</button>
      </div>

      <div v-if="query.trim() && listOpen" class="manual-row small">
        <span class="muted">{{ off.loading ? "Ищем в Open Food Facts…" : "Нет нужного?" }}</span>
        <button type="button" class="text" @click="enterManually">✏️ {{ isCode ? "Ввести со штрихкодом" : "Ввести вручную" }}</button>
      </div>

      <div v-if="query.trim() && listOpen" class="list" role="listbox">
        <template v-if="localRows.length">
          <div class="group">В приложении</div>
          <div v-for="v in localRows" :key="v.id" class="opt" role="option" tabindex="0"
               @click="pickLocal(v)" @keydown.enter.prevent="pickLocal(v)">
            <span class="lbl"><span>{{ v.name }}</span><span class="sub">{{ v.subFull }}</span></span>
            <span v-if="v.kbjuMissing" class="right">нет КБЖУ</span>
            <span v-else class="right"><span>{{ fmt(v.calories) }} ккал</span><span class="tiny">{{ bjuOf(v) }}</span></span>
          </div>
        </template>
        <div v-else-if="!isCode" class="opt muted small">В приложении не нашли</div>

        <template v-if="offRows.length">
          <div class="group">Open Food Facts</div>
          <div v-for="(s, i) in offRows" :key="s.barcode || i" class="opt off" role="option" tabindex="0"
               @click="pickOff(s)" @keydown.enter.prevent="pickOff(s)">
            <span class="lbl"><span>{{ s.name }}</span><span class="sub">{{ offSub(s) }}</span></span>
            <span class="right"><span>{{ offKcal(s) }}</span><span class="tiny">{{ bjuOf(s) }}</span></span>
          </div>
        </template>
        <div v-if="hint" class="opt muted small">{{ hint }}</div>
        <div v-else-if="off.error" class="opt small err">{{ off.error }}</div>
        <div v-else-if="off.done && !offRows.length" class="opt muted small">В Open Food Facts тоже не нашли — введите вручную.</div>
        <div v-if="!isCode && !off.done && !off.loading && localRows.length && query.trim().length >= 2" class="opt more">
          <button type="button" class="text" @click="search(query)">Нет нужного? Искать в Open Food Facts</button>
        </div>
      </div>
    </template>

    <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onScan" />
  </div>
</template>

<style scoped>
.finder { display: flex; flex-direction: column; gap: 8px; }
p { margin: 0; }
.chosen { display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 14px; border-radius: var(--r-in); background: var(--enamel-2); border: 1.5px solid var(--line); }
.what { flex: 1; min-width: 0; }
.sub { display: block; font-size: 12px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--rim-soft); color: var(--rim); white-space: nowrap; }
.nokbju { display: flex; flex-direction: column; gap: 8px; padding: 12px; border-radius: var(--r-in); background: var(--beak-soft); }
.end { display: flex; justify-content: flex-end; }
.err { color: var(--tomato); }
.bar { display: flex; gap: 8px; }
.clearable { position: relative; flex: 1; min-width: 0; }
.clearable input { padding-right: 44px; }
.x { position: absolute; right: 2px; top: 50%; transform: translateY(-50%); min-height: 40px; min-width: 40px; padding: 0; border: 0; color: var(--muted); font-weight: 400; }
.cam { padding: 0 12px; flex: none; }
.manual-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.list { max-height: min(340px, 38vh); overflow-y: auto; overscroll-behavior: contain; background: var(--enamel); border: 1.5px solid var(--rim); border-radius: var(--r-in); }
.group { padding: 8px 12px 2px; font-size: 12px; color: var(--muted); font-weight: 600; }
.opt { display: flex; justify-content: space-between; gap: 10px; padding: 9px 12px; cursor: pointer; min-height: 44px; align-items: center; }
.opt:hover, .opt:focus-visible { background: var(--rim-soft); outline: none; }
.opt.off .lbl > span:first-child { color: var(--graphite); }
.opt.more { cursor: default; }
.opt.more:hover { background: none; }
.lbl { min-width: 0; display: flex; flex-direction: column; }
.right { display: flex; flex-direction: column; align-items: flex-end; flex: none; color: var(--muted); font-size: 13px; white-space: nowrap; }
</style>
