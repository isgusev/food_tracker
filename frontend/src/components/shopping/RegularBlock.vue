<script setup lang="ts">
// «Обычно берём»: товары, которые покупают почти каждую неделю, — предложение «карандашом» (как черновик автоплана).
// В список — по «+» или «Добавить всё» (строка ведёт себя как ручная добавка); ✕ — больше не предлагать.
import { computed, ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast, toastError } from "../../session";
import { lineQty, pkgText, type ShopList } from "../../shopping";
import { fmt, fmtQty, local, num } from "../../util";

type Regular = Schemas["RegularOut"];
type Item = Schemas["RegularItem"];
const props = defineProps<{ list: ShopList }>();
const emit = defineEmits<{ changed: [list: ShopList] }>();

const data = ref<Regular | null>(null);
const busy = ref(false);
const open = ref(local.get("ft.regularOpen", true));
watch(open, (v) => local.set("ft.regularOpen", v));

async function load() {
  try {
    data.value = await ok(api.GET("/api/v1/shopping-list/regular", {
      params: { query: { start_date: props.list.start_date, end_date: props.list.end_date } } }));
  } catch { data.value = null; }
}
watch(() => `${props.list.id}:${props.list.updated_at}:${props.list.lines.length}`, load, { immediate: true });

const qty = (r: Item) => lineQty({ ...r, needed: r.to_buy });
const addOne = (r: Item) => ok(api.POST("/api/v1/shopping-lists/{list_id}/lines", {
  params: { path: { list_id: props.list.id } }, body: { product_id: r.product_id, quantity: qty(r) } }));
async function add(r: Item) {
  busy.value = true;
  try { emit("changed", await addOne(r)); toast(`«${r.name}» — в списке`); }
  catch (e) { toastError(e); } finally { busy.value = false; }
}
async function addAll() {
  if (!data.value) return;
  busy.value = true;
  let res: ShopList | null = null;
  try {
    for (const r of data.value.items) res = await addOne(r);
    toast(`Добавлено: ${data.value.items.length}`);
  } catch (e) { toastError(e); } finally { busy.value = false; if (res) emit("changed", res); }
}
async function never(r: Item) {
  try {
    await ok(api.PATCH("/api/v1/stock/items/{product_id}", { params: { path: { product_id: r.product_id } }, body: { regular: "never" } }));
    toast(`«${r.name}» больше не предлагаем`);
    await load();
  } catch (e) { toastError(e); }
}
const snacks = computed(() => data.value?.snacks);
const quotaPct = computed(() => (snacks.value?.quota ? Math.min(100, (num(snacks.value.spent) / num(snacks.value.quota)) * 100) : 0));
const why = (r: Item) => (r.always ? "всегда берём" : `брали ${r.weeks_bought} из ${r.weeks} недель`) + ` · ${fmtQty(r.weekly, r.unit)} в неделю`;
</script>

<template>
  <section v-if="data && (data.items.length || snacks?.quota)" class="regular">
    <div class="head">
      <button class="text toggle" :aria-expanded="open" @click="open = !open">
        <span class="swatch" aria-hidden="true"></span><b>Обычно берём</b>
        <span v-if="data.items.length" class="muted small">{{ data.items.length }}</span>
        <span class="muted small" aria-hidden="true">{{ open ? "▴" : "▾" }}</span>
      </button>
      <span class="grow"></span>
      <button v-if="open && data.items.length > 1" class="small" :disabled="busy" @click="addAll">+ Добавить всё</button>
    </div>
    <div v-if="snacks?.quota" class="quota" :class="{ over: num(snacks.spent) >= num(snacks.quota) }">
      <span class="small">Снеки и сладкое на неделе: <b>{{ fmt(snacks.spent) }}</b> из {{ fmt(snacks.quota) }} ₽</span>
      <span class="meter"><i :style="{ width: quotaPct + '%' }"></i></span>
      <span v-if="snacks.hidden" class="tiny muted">Не предлагаем {{ snacks.hidden }} — квота недели кончилась</span>
    </div>
    <template v-if="open">
      <div v-for="r in data.items" :key="r.item_key" class="row">
        <span class="what"><span>{{ r.name }} <span v-if="r.is_snack" class="badge">снек</span></span>
          <span class="tiny muted">{{ why(r) }}</span></span>
        <span class="qty"><b>{{ pkgText({ ...r, needed: r.to_buy }) }}</b>
          <span v-if="r.est_price != null" class="tiny muted">≈ {{ fmt(r.est_price) }} ₽</span></span>
        <button class="plus" :disabled="busy" :aria-label="'Добавить: ' + r.name" @click="add(r)">+</button>
        <button class="text x" title="Не предлагать этот товар" :aria-label="'Не предлагать: ' + r.name" @click="never(r)">✕</button>
      </div>
      <p v-if="!data.items.length" class="tiny muted">Всё обычное уже в списке или дома.</p>
    </template>
  </section>
</template>

<style scoped>
/* «карандаш»: пунктир графитом и штриховка — это предложение, а не список */
.regular { padding: 10px 14px; border-radius: var(--r-pot); border: 1.5px dashed var(--graphite); background: var(--graphite-soft);
  display: flex; flex-direction: column; gap: 6px; }
.head { display: flex; align-items: center; gap: 8px; }
.toggle { padding: 0 4px; color: var(--ink); gap: 8px; }
.swatch { width: 18px; height: 18px; border-radius: 5px; border: 1px dashed var(--graphite);
  background: repeating-linear-gradient(45deg, var(--graphite) 0 1.5px, transparent 1.5px 5px); }
.grow { flex: 1; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; border-color: var(--graphite); color: var(--ink); }
.quota { display: flex; flex-direction: column; gap: 4px; }
.meter { height: 8px; border-radius: 999px; background: var(--enamel); border: 1px solid var(--line); overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--graphite); }
.quota.over .meter i { background: var(--tomato); }
.row { display: flex; align-items: center; gap: 10px; padding: 6px 0; border-top: 1px dashed var(--line); }
.what { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.qty { display: flex; flex-direction: column; align-items: flex-end; white-space: nowrap; }
.plus { width: 44px; padding: 0; font-size: 20px; border-color: var(--graphite); color: var(--ink); }
.plus:hover { background: var(--enamel); }
.x { min-width: 40px; padding: 0; color: var(--muted); }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--enamel); color: var(--muted); }
p { margin: 0; }
</style>
