<script setup lang="ts">
// Покупки: общий список семьи на период (план − запасы, до целых упаковок). Отметка «куплено» сразу кладёт товар
// в запасы; без сети — в очередь. Список опрашивается каждые 15 с (видно, что отметили другие).
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api, ok } from "../../api/client";
import { ensureCatalog, loadProducts } from "../../catalog";
import BoughtModal from "../../components/shopping/BoughtModal.vue";
import ExtraModal from "../../components/shopping/ExtraModal.vue";
import PackageModal from "../../components/shopping/PackageModal.vue";
import RegularBlock from "../../components/shopping/RegularBlock.vue";
import { toast, toastError } from "../../session";
import { flushQueue, lineQty, pkgText, queue, toggleLine, withQueue, type Line, type ShopList } from "../../shopping";
import { addDays, dayMonth, dayMonthShort, fmt, fmtQty, num, startOfWeek, today } from "../../util";

// чек — отдельным куском: сканер и разбор нужны раз в поход в магазин
const ReceiptModal = defineAsyncComponent(() => import("../../components/shopping/ReceiptModal.vue"));

const POLL_MS = 15000;
const route = useRoute();
const qStart = typeof route.query.start === "string" ? route.query.start : "";
const qEnd = typeof route.query.end === "string" ? route.query.end : "";

const lst = ref<ShopList | null>(null);
const loaded = ref(false);
const loading = ref(false);
const start = ref(qStart || today());
const end = ref(qEnd || addDays(startOfWeek(today()), 6));
const periodOpen = ref(false);
const editing = ref<Line | null>(null);
const packaging = ref<Line | null>(null);
const extraOpen = ref(false);
const receiptOpen = ref(false);
const receiptsReady = ref(0);
const busyLine = ref<number | null>(null);

// оценка суммы — по последней цене товара из прошлых покупок
const prices = ref<Record<string, number>>({});
const estimate = (l: Line) => {
  const p = l.item_key ? prices.value[l.item_key] : undefined;
  return p != null && lineQty(l) > 0 ? p * lineQty(l) : null;
};

async function refresh(silent = true) {
  await flushQueue();
  try {
    lst.value = withQueue(await ok(api.GET("/api/v1/shopping-lists/active")));
    if (lst.value && !qStart) { start.value = lst.value.start_date; end.value = lst.value.end_date; }
  } catch (e) { if (!silent) toastError(e); }
  loaded.value = true;
}
async function generate() {
  if (end.value < start.value) { toast("Дата окончания раньше даты начала", "error"); return; }
  loading.value = true;
  try {
    lst.value = await ok(api.POST("/api/v1/shopping-lists", { body: { start_date: start.value, end_date: end.value } }));
    periodOpen.value = false;
    toast("Список обновлён по плану и запасам");
  } catch (e) { toastError(e); } finally { loading.value = false; }
}
async function loadReceiptsReady() {
  try { receiptsReady.value = (await ok(api.GET("/api/v1/receipts"))).filter((r) => r.status === "done").length; }
  catch { receiptsReady.value = 0; }
}

let timer: ReturnType<typeof setInterval> | undefined;
const modalOpen = () => !!(editing.value || packaging.value || extraOpen.value || receiptOpen.value);
const onVisible = () => { if (!document.hidden) { refresh(); loadReceiptsReady(); } };
const onOnline = () => { flushQueue().then(() => refresh()); };
onMounted(async () => {
  ok(api.GET("/api/v1/finance/prices"))
    .then((r) => { prices.value = Object.fromEntries(r.map((p) => [p.item_key, num(p.unit_price)])); }).catch(() => {});
  loadReceiptsReady();
  ensureCatalog().catch(() => {});
  await refresh(false);
  // пришли из плана с периодом — сразу формируем за него
  if (qStart && (!lst.value || lst.value.start_date !== start.value || lst.value.end_date !== end.value)) await generate();
  if (!lst.value) periodOpen.value = true;
  timer = setInterval(() => { if (!document.hidden && !modalOpen() && navigator.onLine) refresh(); }, POLL_MS);
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("online", onOnline);
});
onBeforeUnmount(() => {
  clearInterval(timer);
  document.removeEventListener("visibilitychange", onVisible);
  window.removeEventListener("online", onOnline);
});

const toBuy = computed(() => (lst.value?.lines ?? []).filter((l) => !l.is_checked));
const groups = computed(() => {
  const map = new Map<string, Line[]>();
  for (const l of toBuy.value) {
    const g = l.category_name || "Без категории";
    if (!map.has(g)) map.set(g, []);
    map.get(g)!.push(l);
  }
  return [...map.entries()].map(([name, list]) => ({ name, list }));
});
const bought = computed(() => (lst.value?.lines ?? []).filter((l) => l.is_checked));
const spent = computed(() => bought.value.reduce((s, l) => s + num(l.price), 0));
const estTotal = computed(() => {
  let sum = 0, unknown = 0;
  for (const l of toBuy.value) { const e = estimate(l); if (e == null) unknown++; else sum += e; }
  return { sum, unknown };
});

async function toggle(l: Line, kind: "check" | "uncheck") {
  busyLine.value = l.id;
  try { const res = await toggleLine(l, kind); if (res) lst.value = res; }
  catch (e) { toastError(e); } finally { busyLine.value = null; }
}
async function remove(l: Line) {
  try {
    lst.value = await ok(api.DELETE("/api/v1/shopping-lists/lines/{line_id}", { params: { path: { line_id: l.id } } }));
  } catch (e) { toastError(e); }
}
async function closeList() {
  if (!lst.value) return;
  const unpriced = bought.value.filter((l) => l.price == null).length;
  if (!confirm(`Закрыть список?${unpriced ? `\nУ ${unpriced} покупок не указана цена — её можно будет дописать в запасах.` : ""}`)) return;
  try {
    await ok(api.POST("/api/v1/shopping-lists/{list_id}/close", { params: { path: { list_id: lst.value.id } } }));
    lst.value = null;
    periodOpen.value = true;
    toast("Список закрыт");
  } catch (e) { toastError(e); }
}
function preset(kind: "rest" | "next" | "3d") {
  const t = today(), w = startOfWeek(t);
  if (kind === "rest") { start.value = t; end.value = addDays(w, 6); }
  if (kind === "next") { start.value = addDays(w, 7); end.value = addDays(w, 13); }
  if (kind === "3d") { start.value = t; end.value = addDays(t, 2); }
}
async function copy() {
  const text = groups.value.map((g) => `${g.name}:\n` + g.list.map((l) => `☐ ${l.product_name} — ${pkgText(l)}`).join("\n")).join("\n\n");
  try { await navigator.clipboard.writeText(text); toast("Список скопирован"); }
  catch { toast("Не удалось скопировать", "error"); }
}
const needsPackage = (l: Line) => !l.package_amount && !l.is_staple && l.unit !== "pcs";
async function onPackageSaved() {
  packaging.value = null;
  loadProducts().catch(() => {});   // новая упаковка нужна и поиску («Внеплановая покупка»)
  if (!lst.value) return;
  try {
    lst.value = await ok(api.POST("/api/v1/shopping-lists", { body: { start_date: lst.value.start_date, end_date: lst.value.end_date } }));
    toast("Упаковка сохранена — список пересчитан");
  } catch (e) { toastError(e); }
}
function onExtraSaved(res: ShopList) { lst.value = res; extraOpen.value = false; toast("Добавлено в список"); }
function onBoughtSaved(res: ShopList) { lst.value = res; editing.value = null; }
function onReceiptDone(applied: boolean) { receiptOpen.value = false; if (applied) refresh(); loadReceiptsReady(); }
const brandLine = (l: Line) => (l.is_exact || !l.brand ? "" : l.is_extra ? l.brand : `обычно ${l.brand}`);
</script>

<template>
  <div class="shop">
    <header class="head">
      <h1 class="display">Покупки</h1>
      <button :class="receiptsReady ? 'fill' : ''" title="Загрузить покупки и цены из чека по QR-коду" @click="receiptOpen = true">
        🧾 Чек<template v-if="receiptsReady"> · готов{{ receiptsReady > 1 ? " " + receiptsReady : "" }}</template></button>
    </header>

    <!-- период: свёрнут в строку, пока есть список -->
    <section class="period inset">
      <div v-if="lst && !periodOpen" class="period-line">
        <span><b>{{ dayMonthShort(lst.start_date) }} — {{ dayMonth(lst.end_date) }}</b>
          <span class="muted small"> · по плану и запасам</span></span>
        <span class="grow"></span>
        <button class="text small" @click="periodOpen = true">Другой период</button>
        <button class="small" :disabled="loading" @click="generate">{{ loading ? "Считаю…" : "Пересчитать" }}</button>
      </div>
      <template v-else>
        <div class="dates">
          <label class="field"><span class="lbl">С</span><input v-model="start" type="date"></label>
          <label class="field"><span class="lbl">По</span><input v-model="end" type="date"></label>
          <button class="fill" :disabled="loading" @click="generate">{{ loading ? "Считаю…" : lst ? "Пересчитать" : "Сформировать список" }}</button>
          <button v-if="lst" class="text" @click="periodOpen = false">Отмена</button>
        </div>
        <div class="chips">
          <button class="chip" @click="preset('rest')">До конца недели</button>
          <button class="chip" @click="preset('next')">Следующая неделя</button>
          <button class="chip" @click="preset('3d')">3 дня</button>
        </div>
        <p class="tiny muted">Считается из плана: несъеденные порции блюд, которых нет в холодильнике, минус то, что уже есть дома,
          до целых упаковок. Список общий — отметки «куплено» видны на всех телефонах, товар сразу попадает в «Холодильник → Продукты».</p>
      </template>
    </section>

    <p v-if="loaded && !lst" class="muted">Активного списка нет — выберите период и сформируйте.</p>

    <template v-if="lst">
      <RegularBlock :list="lst" @changed="lst = $event" />

      <!-- главный контейнер — то, что ещё купить -->
      <section class="pot list">
        <div class="list-head">
          <span class="display count">{{ toBuy.length }}</span>
          <span class="small"><b>осталось купить</b><span class="muted"> · куплено {{ bought.length }}</span>
            <template v-if="estTotal.sum"><br><span class="muted">≈ {{ fmt(estTotal.sum) }} ₽<template v-if="estTotal.unknown"> + {{ estTotal.unknown }} без цены</template></span></template></span>
          <span class="grow"></span>
          <span v-if="queue.items.length" class="badge warn" title="Отметки без сети — отправятся, когда связь вернётся">не отправлено: {{ queue.items.length }}</span>
        </div>

        <p v-if="!toBuy.length" class="empty small muted">{{ bought.length ? "Всё купили." : "Покупать нечего — всё есть дома или план пуст." }}</p>
        <template v-for="g in groups" :key="g.name">
          <h2 class="cat">{{ g.name }}</h2>
          <div v-for="l in g.list" :key="l.id" class="line">
            <button class="tick" role="checkbox" aria-checked="false" :aria-label="'Купил: ' + l.product_name"
                    :disabled="busyLine === l.id" @click="toggle(l, 'check')"></button>
            <span class="what">
              <span class="name">{{ l.product_name }}
                <span v-if="l.is_staple" class="badge warn">заканчивается</span>
                <span v-if="l.is_extra" class="badge">вне плана</span>
                <span v-if="l.is_exact" class="badge warn" title="Нужен именно этот бренд">🎯 {{ l.brand }}</span></span>
              <span v-if="brandLine(l)" class="tiny muted">{{ brandLine(l) }}</span>
            </span>
            <span class="qty">
              <b>{{ pkgText(l) }}</b>
              <span v-if="estimate(l) != null" class="tiny muted">≈ {{ fmt(estimate(l)) }} ₽</span>
              <button v-if="needsPackage(l)" class="text pack" title="У товара нет упаковки — укажите, и покупка округлится до целых пачек"
                      @click="packaging = l">📦 пачка?</button>
            </span>
            <button class="text x" :aria-label="'Убрать из списка: ' + l.product_name" title="Убрать из списка" @click="remove(l)">✕</button>
          </div>
        </template>
        <button class="add" @click="extraOpen = true">+ Внеплановая покупка</button>
      </section>

      <section v-if="bought.length" class="bought">
        <div class="bought-head small muted"><span>Куплено — уже в запасах</span><span v-if="spent" class="nowrap">потрачено {{ fmt(spent, 2) }} ₽</span></div>
        <div v-for="l in bought" :key="l.id" class="line done">
          <button class="tick on" role="checkbox" aria-checked="true" :aria-label="'Не купил: ' + l.product_name"
                  :disabled="busyLine === l.id" @click="toggle(l, 'uncheck')">✓</button>
          <span class="what"><span class="name">{{ l.product_name }}</span>
            <span class="tiny muted">{{ fmtQty(l.bought_quantity, l.unit) }}<template v-if="l.price != null"> · {{ fmt(l.price, 2) }} ₽</template><template v-if="l.expires_on"> · до {{ dayMonthShort(l.expires_on) }}</template></span></span>
          <button class="small" :class="{ text: l.price != null }" @click="editing = l">{{ l.price == null ? "Цена…" : "Изменить" }}</button>
        </div>
      </section>

      <div class="foot">
        <button class="text small" :disabled="!toBuy.length" @click="copy">Копировать список</button>
        <button class="text small" @click="closeList">Закрыть список</button>
      </div>
    </template>

    <BoughtModal v-if="editing" :line="editing" @close="editing = null" @saved="onBoughtSaved" />
    <PackageModal v-if="packaging" :line="packaging" @close="packaging = null" @saved="onPackageSaved" />
    <ExtraModal v-if="extraOpen && lst" :list-id="lst.id" @close="extraOpen = false" @saved="onExtraSaved" />
    <ReceiptModal v-if="receiptOpen" @close="onReceiptDone(false)" @applied="onReceiptDone(true)" />
  </div>
</template>

<style scoped>
.shop { display: flex; flex-direction: column; gap: 14px; max-width: 760px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
h1 { font-size: 32px; color: var(--rim); }
.foot { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; }
.period { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
.period-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; }
.dates { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 4px; width: 170px; }
.lbl { font-size: 14px; font-weight: 600; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { min-height: 36px; padding: 0 14px; font-size: 14px; font-weight: 500; border-color: var(--line); color: var(--ink); background: var(--enamel); }
.chip:hover { border-color: var(--rim); }
p { margin: 0; }
.grow { flex: 1; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }

.list { padding: 14px 16px 16px; display: flex; flex-direction: column; }
.list-head { display: flex; align-items: center; gap: 12px; padding-bottom: 6px; }
.count { font-size: 40px; color: var(--rim); }
.empty { padding: 10px 0; }
.cat { font-size: 14px; font-weight: 600; color: var(--muted); margin: 14px 0 2px; }
.line { display: flex; align-items: center; gap: 12px; padding: 8px 0; border-top: 1px solid var(--line); min-height: 56px; }
.cat + .line { border-top: 0; }
/* «галочка» — крупная круглая цель: в магазине телефон в одной руке */
.tick { flex: none; width: 44px; height: 44px; min-height: 44px; padding: 0; border-radius: 50%; border: 2px solid var(--rim);
  background: var(--enamel); color: var(--on-fill); font-size: 20px; }
.tick:hover { background: var(--rim-soft); }
.tick.on { background: var(--rim); }
.what { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.name { overflow-wrap: anywhere; }
.qty { display: flex; flex-direction: column; align-items: flex-end; text-align: right; white-space: nowrap; }
.pack { min-height: 32px; padding: 0 4px; font-size: 13px; font-weight: 500; color: var(--cook); }
.x { min-width: 40px; padding: 0; color: var(--muted); }
.add { margin-top: 10px; width: 100%; min-height: 48px; border: 2px dashed var(--rim); border-radius: var(--r-in); }
.add:hover { background: var(--rim-soft); }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); font-weight: 500; white-space: nowrap; }
.badge.warn { background: var(--beak-soft); color: var(--cook); }

.bought { padding: 10px 16px; border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); }
.nowrap { white-space: nowrap; }
.bought-head { display: flex; justify-content: space-between; gap: 8px; padding-bottom: 4px; }
.done .name { color: var(--muted); text-decoration: line-through; text-decoration-color: var(--line); }
.bought-head + .line { border-top: 0; }
@media (max-width: 600px) {
  .field { width: calc(50% - 5px); }
  .dates .fill { width: 100%; }
}
</style>
