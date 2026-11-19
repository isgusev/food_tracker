<script setup lang="ts">
// Чек по QR: строка QR → расшифровка (code-qr.ru → ФНС) → сопоставление строк чека со списком покупок и справочником
// → проверка → «Сохранить покупки». Чек доходит до налоговой с задержкой: «ждём» — нормальное состояние, чек сохранён.
// Запрос статуса проверку из пакета не тратит (тратит только новый чек — POST /receipts).
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, loadProducts } from "../../catalog";
import { toast } from "../../session";
import type { Line } from "../../shopping";
import { UNIT_LABEL, dateTime, fmt, fuzzyScore, local, num } from "../../util";
import ItemPicker, { type PickerItem } from "../ItemPicker.vue";
import ModalSheet from "../ModalSheet.vue";
import BarcodeScanner from "../finder/BarcodeScanner.vue";

type Receipt = Schemas["ReceiptOut"];
type ReceiptItem = Schemas["ReceiptItemOut"];
type Product = Schemas["ProductResponse"];
const emit = defineEmits<{ close: []; applied: [] }>();

const LAST_CATEGORY = "ft.lastProductCategory";
const SIZE_RE = /(\d+(?:[.,]\d+)?)\s*(кг|гр|г|мл|л)(?![а-яa-z])/gi;
const STATUS: Record<string, string> = { pending: "ждём ФНС", done: "проверить", error: "ошибка", applied: "сохранён" };
const SOURCE: Record<string, string> = { alias: "запомнено", list: "из списка", catalog: "похоже", none: "" };

/** Название нового продукта из строки чека: без размера, «,кг», «вес», лишних пробелов. */
function cleanName(name: string): string {
  const s = name.replace(SIZE_RE, " ").replace(/[,;]\s*(кг|шт|вес)\.?\s*$/i, " ").replace(/(?<![а-яё])вес(?![а-яё])\.?/gi, " ")
    .replace(/\s+/g, " ").replace(/[\s,.;:-]+$/, "").trim();
  return s ? s[0].toUpperCase() + s.slice(1) : name.trim();
}
/** Упаковка из названия («930мл» → 930 мл); у весового товара упаковки нет. */
function packOf(item: ReceiptItem): { amount: number; unit: string } | null {
  if (num(item.quantity) % 1 || /(?<![а-яё])вес(?![а-яё])|,\s*кг\s*$/i.test(item.name)) return null;
  const all = [...item.name.matchAll(SIZE_RE)];
  if (!all.length) return null;
  const [, n, u] = all[all.length - 1];
  const v = Number(n.replace(",", ".")), unit = u.toLowerCase();
  if (!(v > 0)) return null;
  if (unit === "кг") return { amount: v * 1000, unit: "g" };
  if (unit === "л") return { amount: v * 1000, unit: "ml" };
  return { amount: v, unit: unit === "мл" ? "ml" : "g" };
}

/** Решение по строке чека: choice = "skip" | "line:<id>" | "product" | "new" (завести по названию без КБЖУ). */
interface Row {
  index: number; item: ReceiptItem; source: string; confidence: number;
  choice: string; product_id: number | null; quantity: number | string; qtyEdited: boolean;
  newName: string; newCategory: string;
}
function rowFrom(item: ReceiptItem, lines: Line[]): Row {
  const s = item.suggestion ?? { action: "skip", source: "none" } as Schemas["Suggestion"];
  let choice = "skip";
  if (s.action === "list" && s.shopping_line_id && lines.some((l) => l.id === s.shopping_line_id)) choice = `line:${s.shopping_line_id}`;
  else if (s.action !== "skip" && s.product_id) choice = "product";
  return {
    index: item.index, item, source: s.source, confidence: s.confidence || 0, choice, product_id: s.product_id ?? null,
    quantity: s.quantity != null ? num(s.quantity) : "", qtyEdited: false,
    newName: cleanName(item.name), newCategory: local.get<string>(LAST_CATEGORY, "") || "Прочее",
  };
}

const receipt = ref<Receipt | null>(null);
const recent = ref<Schemas["ReceiptBrief"][]>([]);
const lines = ref<Line[]>([]);          // неотмеченные строки активного списка
const rows = ref<Row[]>([]);
const qr = ref("");
const scanning = ref(false);
const busy = ref(false);
const error = ref("");

async function loadContext() {
  try { recent.value = await ok(api.GET("/api/v1/receipts")); } catch { /* не критично */ }
  try { lines.value = ((await ok(api.GET("/api/v1/shopping-lists/active")))?.lines ?? []).filter((l) => !l.is_checked); }
  catch { lines.value = []; }
}
onMounted(() => { loadContext(); if (!catalog.loaded.products) loadProducts().catch(() => {}); });

// «ждущий» чек опрашиваем сами, пока окно открыто: первую минуту — каждые 4 с, до 3 минут — каждые 15 с;
// дальше его проверит сервер в фоне
const polling = ref(false);
const nextIn = ref(0);
let pollTimer: ReturnType<typeof setTimeout> | undefined, tickTimer: ReturnType<typeof setInterval> | undefined, pollStarted = 0;
function stopPolling() { clearTimeout(pollTimer); clearInterval(tickTimer); polling.value = false; }
function schedulePoll() {
  const elapsed = Date.now() - pollStarted;
  if (elapsed > 180000) { stopPolling(); return; }
  const delay = elapsed < 60000 ? 4000 : 15000;
  polling.value = true;
  nextIn.value = Math.round(delay / 1000);
  clearInterval(tickTimer);
  tickTimer = setInterval(() => { nextIn.value = Math.max(0, nextIn.value - 1); }, 1000);
  pollTimer = setTimeout(async () => {
    if (!receipt.value) return stopPolling();
    try { show(await ok(api.GET("/api/v1/receipts/{receipt_id}", { params: { path: { receipt_id: receipt.value.id } } })), true); }
    catch { schedulePoll(); }
  }, delay);
}
onBeforeUnmount(stopPolling);

function show(r: Receipt, fromPoll = false) {
  receipt.value = r;
  rows.value = r.status === "done" ? (r.items ?? []).map((it) => rowFrom(it, lines.value)) : [];
  if (r.status !== "pending") { stopPolling(); return; }
  if (!fromPoll) pollStarted = Date.now();
  schedulePoll();
}
async function submit(text?: string) {
  scanning.value = false;
  const q = (text ?? qr.value).trim();
  if (q.length < 10) { error.value = "Отсканируйте QR-код чека или вставьте строку из него"; return; }
  error.value = ""; busy.value = true;
  try { show(await ok(api.POST("/api/v1/receipts", { body: { qr: q } }))); }
  catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
async function open(id: number) {
  error.value = ""; busy.value = true;
  try { show(await ok(api.GET("/api/v1/receipts/{receipt_id}", { params: { path: { receipt_id: id } } }))); }
  catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
function back() { stopPolling(); receipt.value = null; error.value = ""; loadContext(); }

const productItems = computed<PickerItem[]>(() => catalog.products.map((p) => ({ id: p.id, label: p.name, sub: p.brand?.name || "" })));
const productById = computed<Record<number, Product>>(() => Object.fromEntries(catalog.products.map((p) => [p.id, p])));
const lineById = computed<Record<number, Line>>(() => Object.fromEntries(lines.value.map((l) => [l.id, l])));
function unitOf(r: Row): string {
  if (r.choice.startsWith("line:")) return lineById.value[Number(r.choice.slice(5))]?.unit || "g";
  if (r.choice === "new") return packOf(r.item)?.unit || "g";
  return (r.product_id ? productById.value[r.product_id]?.base_unit : null) || r.item.suggestion?.unit || "g";
}
/** «Новый продукт»: сначала покажем похожие из справочника — вдруг он уже есть. */
function similar(r: Row): Product[] {
  const name = r.newName.trim();
  if (name.length < 3) return [];
  return catalog.products
    .map((p) => ({ p, s: Math.max(fuzzyScore(name, `${p.name} ${p.brand?.name || ""}`), fuzzyScore(p.name, name)) }))
    .filter((x) => x.s >= 0.6).sort((a, b) => b.s - a.s).slice(0, 3).map((x) => x.p);
}
function useExisting(r: Row, p: Product) { r.choice = "product"; r.product_id = p.id; }
// одна строка списка — одной строке чека
const usedLines = computed(() => new Set(rows.value.filter((r) => r.choice.startsWith("line:")).map((r) => r.choice)));
const chosen = computed(() => rows.value.filter((r) => r.choice !== "skip"));
const chosenSum = computed(() => chosen.value.reduce((s, r) => s + num(r.item.sum), 0));
const brandOf = (p: Product) => (p.brand && p.brand.name !== "Без бренда" ? p.brand.name : "");

async function apply() {
  if (!receipt.value) return;
  error.value = "";
  const noProduct = rows.value.find((r) => r.choice === "product" && !r.product_id);
  if (noProduct) { error.value = `Выберите продукт для «${noProduct.item.name}» или пропустите строку`; return; }
  const noName = rows.value.find((r) => r.choice === "new" && !(r.newName.trim() && r.newCategory.trim()));
  if (noName) { error.value = `Укажите название и категорию нового продукта для «${noName.item.name}»`; return; }
  busy.value = true;
  try {
    // новые продукты — в справочник без КБЖУ (тот же по названию не задвоится)
    let created = false;
    for (const r of rows.value.filter((x) => x.choice === "new")) {
      const pk = packOf(r.item);
      const p = await ok(api.POST("/api/v1/products/with-category", { body: {
        category_name: r.newCategory.trim(), name: r.newName.trim(), reuse_existing: true,
        package_amount: pk?.amount ?? null, package_unit: pk ? pk.unit : null,
      } as Schemas["ProductWithCategoryCreate"] }));
      local.set(LAST_CATEGORY, r.newCategory.trim());
      r.product_id = p.id; r.choice = "product"; created = true;
    }
    if (created) await loadProducts();
    const body: Schemas["ApplyLine"][] = rows.value.map((r) => {
      if (r.choice === "skip") return { index: r.index, action: "skip" };
      const line: Schemas["ApplyLine"] = { index: r.index, action: "extra", price: num(r.item.sum) };
      if (r.qtyEdited && num(r.quantity) > 0) line.quantity = num(r.quantity);
      if (r.choice.startsWith("line:")) return { ...line, action: "list", shopping_line_id: Number(r.choice.slice(5)) };
      return { ...line, product_id: r.product_id };
    });
    await ok(api.POST("/api/v1/receipts/{receipt_id}/apply", { params: { path: { receipt_id: receipt.value.id } }, body: { lines: body } }));
    toast(`Чек сохранён, покупок: ${chosen.value.length}`);
    emit("applied");
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
const qtyText = (it: ReceiptItem) => fmt(it.quantity, num(it.quantity) % 1 ? 3 : 0);
</script>

<template>
  <ModalSheet title="Чек по QR-коду" wide @close="emit('close')">
    <template v-if="!receipt">
      <button class="fill scan" @click="scanning = true">📷 Сканировать QR чека</button>
      <label class="field"><span class="lbl">…или строка из QR-кода</span>
        <span class="qr"><input v-model="qr" placeholder="t=20261015T2145&s=100.63&fn=…&i=…&fp=…&n=1" @keydown.enter="submit()">
          <button :disabled="busy" @click="submit()">Загрузить</button></span></label>
      <div v-if="recent.length" class="recent">
        <h3>Недавние чеки</h3>
        <button v-for="r in recent" :key="r.id" class="rc" @click="open(r.id)">
          <span class="what"><span>{{ r.store_name || "Чек" }}</span>
            <span class="tiny muted">{{ dateTime(r.purchased_at) }} · {{ r.items_count }} поз.</span></span>
          <span class="right"><span>{{ r.total != null ? fmt(r.total, 2) + " ₽" : "" }}</span>
            <span class="st tiny" :class="r.status">{{ STATUS[r.status] || r.status }}</span></span>
        </button>
      </div>
      <p class="tiny muted">Строки чека сопоставятся со списком покупок и справочником; вы проверите и поправите перед сохранением.
        Сопоставления запоминаются — следующие чеки из того же магазина узнаются сами.</p>
    </template>

    <template v-else>
      <div class="rhead">
        <b>{{ receipt.store_name || "Чек" }}</b>
        <span class="muted small">{{ dateTime(receipt.purchased_at) }}</span>
        <span class="grow"></span>
        <b>{{ receipt.total != null ? fmt(receipt.total, 2) + " ₽" : "" }}</b>
      </div>
      <div v-if="receipt.status === 'pending'" class="note">
        <span v-if="polling">Расшифровываем чек… следующая проверка через {{ nextIn }} с.</span>
        <span v-else>Чек ещё не дошёл до налоговой — так бывает, если у кассы не было связи (иногда часы).
          Он сохранён, приложение само проверит его позже — в «Покупках» появится «🧾 Чек · готов».</span>
        <button class="small" :disabled="busy" @click="open(receipt.id)">Проверить сейчас</button>
      </div>
      <p v-else-if="receipt.status === 'error'" class="err">{{ receipt.error || "Сервис не смог расшифровать чек" }}</p>
      <p v-else-if="receipt.status === 'applied'" class="note">Этот чек уже сохранён в покупки.</p>

      <datalist id="receipt-cat-list"><option v-for="c in catalog.productCategories" :key="c.id" :value="c.name" /></datalist>
      <div v-if="receipt.status === 'done'" class="rows">
        <div v-for="r in rows" :key="r.index" class="rrow" :class="{ skipped: r.choice === 'skip' }">
          <div class="rtop small">
            <span class="rname">{{ r.item.name }}</span>
            <span class="sum muted">{{ qtyText(r.item) }} × {{ fmt(r.item.price, 2) }} = <b>{{ fmt(r.item.sum, 2) }} ₽</b></span>
          </div>
          <div class="pick">
            <select v-model="r.choice" class="choice" :aria-label="'Что это: ' + r.item.name">
              <option value="skip">— не учитывать</option>
              <optgroup v-if="lines.length" label="Из списка покупок">
                <option v-for="l in lines" :key="l.id" :value="'line:' + l.id"
                        :disabled="usedLines.has('line:' + l.id) && r.choice !== 'line:' + l.id">{{ l.product_name }}</option>
              </optgroup>
              <option value="product">Другой продукт из справочника…</option>
              <option value="new">Новый продукт — нет в справочнике…</option>
            </select>
            <template v-if="r.choice !== 'skip'">
              <input v-model="r.quantity" type="number" min="0.1" step="any" inputmode="decimal" class="q" placeholder="авто"
                     aria-label="Количество" @input="r.qtyEdited = true">
              <span class="small muted">{{ UNIT_LABEL[unitOf(r)] }}</span>
            </template>
          </div>
          <ItemPicker v-if="r.choice === 'product'" :items="productItems" :model-value="r.product_id" placeholder="Найти в справочнике…"
                      @update:model-value="r.product_id = Number($event)" />
          <div v-if="r.choice === 'new'" class="new">
            <div class="pick">
              <input v-model="r.newName" class="choice" placeholder="Название продукта" aria-label="Название нового продукта">
              <input v-model="r.newCategory" list="receipt-cat-list" class="cat" placeholder="Категория" aria-label="Категория">
            </div>
            <div v-if="similar(r).length" class="tiny sim">
              <span class="muted">Похожие уже есть:</span>
              <button v-for="p in similar(r)" :key="p.id" class="text simb" title="Взять этот продукт вместо нового" @click="useExisting(r, p)">
                {{ p.name }}<template v-if="brandOf(p)"> · {{ brandOf(p) }}</template></button>
            </div>
            <span class="tiny muted">Сохранится в справочник без КБЖУ — внесёте, когда добавите продукт в план или рецепт.</span>
          </div>
          <span v-if="r.choice !== 'skip' && SOURCE[r.source]" class="tiny muted">
            {{ SOURCE[r.source] }}{{ r.source !== "alias" ? " · " + Math.round(r.confidence * 100) + " %" : "" }}</span>
        </div>
      </div>
    </template>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <BarcodeScanner v-if="scanning" qr title="QR-код чека" @close="scanning = false" @code="submit" />
    <template #foot>
      <button v-if="receipt" class="text" @click="back">← Другой чек</button>
      <span class="grow"></span>
      <button class="text" @click="emit('close')">{{ receipt?.status === "done" ? "Отмена" : "Закрыть" }}</button>
      <button v-if="receipt?.status === 'done'" class="fill" :disabled="busy" @click="apply">
        Сохранить {{ chosen.length }} покуп. · {{ fmt(chosenSum, 2) }} ₽</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
h3 { font-size: 14px; color: var(--muted); }
.grow { flex: 1; }
.scan { align-self: flex-start; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.qr { display: flex; gap: 8px; }
.qr input { flex: 1; min-width: 0; }
.recent { display: flex; flex-direction: column; gap: 4px; }
.rc { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 52px; padding: 6px 12px; border: 0; border-radius: var(--r-in);
  background: var(--enamel-2); color: var(--ink); font-weight: 400; text-align: left; }
.rc:hover { background: var(--rim-soft); }
.what { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.right { display: flex; flex-direction: column; align-items: flex-end; white-space: nowrap; }
.st.done { color: var(--cook); font-weight: 600; }
.st.error { color: var(--tomato); }
.rhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
.note { padding: 10px 12px; border-radius: var(--r-in); background: var(--enamel-2); display: flex; flex-direction: column; align-items: flex-start; gap: 8px; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
.rows { display: flex; flex-direction: column; gap: 8px; }
.rrow { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border: 1.5px solid var(--line); border-radius: var(--r-in); }
.rrow.skipped { opacity: 0.6; border-style: dashed; }
.rtop { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.rname { min-width: 0; overflow-wrap: anywhere; }
.sum { white-space: nowrap; }
.pick { display: flex; align-items: center; gap: 8px; }
.choice { flex: 1; min-width: 0; }
.q { width: 88px; flex: none; }
.cat { width: 40%; flex: none; }
.new { display: flex; flex-direction: column; gap: 6px; }
.sim { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
.simb { min-height: 32px; padding: 0 8px; font-size: 12px; font-weight: 500; }
.err { color: var(--tomato); }
</style>
