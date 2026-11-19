<script setup lang="ts">
// Карточка товара в запасах: партии по сроку (раньше — выше), «📦 Сроки», уточнить остаток, списать,
// базовый / заканчивается, «Обычно берём», снек, история движений. Всё адресуется product_id — сервер сам
// переходит к товару (item_key).
import { computed, onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast, toastError } from "../../session";
import { UNIT_LABEL, dayMonthShort, fmt, fmtQty, num, today } from "../../util";
import ModalSheet from "../ModalSheet.vue";
import SplitLotModal from "./SplitLotModal.vue";
import { REASON } from "./packs";

type StockItem = Schemas["StockItem"];
type Lot = Schemas["LotResponse"];

const props = defineProps<{ item: StockItem }>();
const emit = defineEmits<{ close: []; saved: [list: StockItem[]] }>();

const it = ref<StockItem>(props.item);
const actual = ref<number | string>(num(props.item.remaining));
const woQty = ref<number | string>("");
const woNote = ref("");
const history = ref<Schemas["MovementResponse"][]>([]);
const splitting = ref<Lot | null>(null);
const busy = ref(false);
const regQty = ref<number | string>(props.item.regular_qty == null ? "" : num(props.item.regular_qty));
const todayIso = today();
const pid = () => ({ params: { path: { product_id: it.value.product_id } } });

async function loadHistory() {
  try { history.value = await ok(api.GET("/api/v1/stock/items/{product_id}/history", pid())); } catch { /* необязательно */ }
}
onMounted(loadHistory);

/** Список запасов после действия: родителю, а себе — обновлённый товар и история. */
async function applyList(list: StockItem[]) {
  emit("saved", list);
  it.value = list.find((x) => x.item_key === it.value.item_key) || { ...it.value, remaining: "0", lots: [] };
  await loadHistory();
}
async function run(fn: () => Promise<StockItem[]>, msg?: string) {
  busy.value = true;
  try { await applyList(await fn()); if (msg) toast(msg); }
  catch (e) { toastError(e); }
  finally { busy.value = false; }
}
const inventory = () => run(() => ok(api.POST("/api/v1/stock/items/{product_id}/inventory", { ...pid(), body: { quantity: num(actual.value) } })),
  "Остаток уточнён");
const writeOff = () => num(woQty.value) > 0 && run(() => ok(api.POST("/api/v1/stock/items/{product_id}/write-off", {
  ...pid(), body: { quantity: num(woQty.value), note: woNote.value || null } })), "Списано");
const flags = (body: Schemas["ItemFlags"], msg: string) => run(() => ok(api.PATCH("/api/v1/stock/items/{product_id}", { ...pid(), body })), msg);
function onSplit(list: StockItem[]) {
  splitting.value = null;
  emit("saved", list);
  it.value = list.find((x) => x.item_key === it.value.item_key) || it.value;
}
// ближайший срок — сверху: так же холодильник и списывает; без срока — в конце
const lotsByExpiry = computed(() => [...it.value.lots].sort((x, y) =>
  (x.expires_on || "9999").localeCompare(y.expires_on || "9999") || x.id - y.id));
const REGULAR = [
  { key: "auto", label: "Как обычно", msg: "Решает статистика покупок" },
  { key: "always", label: "Всегда предлагать", msg: "Будем предлагать каждую неделю" },
  { key: "never", label: "Не предлагать", msg: "Больше не предлагаем" },
] as const;
const regChanged = computed(() => num(regQty.value) !== num(it.value.regular_qty) || (regQty.value === "") !== (it.value.regular_qty == null));
function dateTime(s?: string | null): string {
  if (!s) return "";
  return new Date(s).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
const onSnack = (e: Event) => {
  const on = (e.target as HTMLInputElement).checked;
  flags({ is_snack: on }, on ? "Считаем в квоту снеков" : "Не снек");
};
</script>

<template>
  <ModalSheet :title="it.name" wide @close="emit('close')">
    <div class="row">
      <span v-if="it.is_staple" class="badge">базовый — остаток не считаем</span>
      <span v-if="it.needs_check" class="badge warn">учёт сбился — уточните остаток</span>
      <span v-if="num(it.expired) > 0" class="badge danger">просрочено {{ fmtQty(it.expired, it.unit) }}</span>
      <span v-if="!it.is_staple" class="small muted">Сейчас: <b>{{ fmtQty(it.remaining, it.unit) }}</b></span>
    </div>

    <div v-if="it.lots.length" class="lots">
      <div v-for="l in lotsByExpiry" :key="l.id" class="lot">
        <div class="grow">
          <div><b :class="{ expired: l.expires_on && l.expires_on < todayIso }">{{ l.expires_on ? "до " + dayMonthShort(l.expires_on) : "срок не указан" }}</b>
            · {{ fmtQty(l.remaining, it.unit) }}<span class="small muted"> из {{ fmtQty(l.quantity, it.unit) }}</span></div>
          <div class="tiny muted ell">{{ dayMonthShort(l.purchased_on) }} · {{ l.brand || "—" }} · {{ REASON[l.source] || l.source }}<template v-if="l.price != null"> · {{ fmt(l.price, 2) }} ₽</template></div>
        </div>
        <button class="small" title="Указать сроки по пачкам (код «Честного знака»)" @click="splitting = l">📦 Сроки</button>
      </div>
    </div>

    <div v-if="!it.is_staple" class="grid2">
      <div class="box">
        <h3>Уточнить остаток</h3>
        <div class="row"><input v-model="actual" type="number" min="0" step="any" inputmode="decimal" class="n3" aria-label="Сколько есть на самом деле">
          <span class="small muted">{{ UNIT_LABEL[it.unit] }}</span>
          <button class="fill small" :disabled="busy" @click="inventory">Так и есть</button></div>
        <span class="tiny muted">Пересчитали дома — запасы станут ровно такими.</span>
      </div>
      <div class="box">
        <h3>Списать</h3>
        <div class="row"><input v-model="woQty" type="number" min="0.1" step="any" inputmode="decimal" class="n3" placeholder="сколько" aria-label="Сколько списать">
          <input v-model="woNote" class="grow" placeholder="испортилось…" aria-label="Причина"></div>
        <div><button class="small danger" :disabled="busy || !num(woQty)" @click="writeOff">Списать</button></div>
      </div>
    </div>

    <div class="row">
      <button class="small" :disabled="busy" @click="flags({ is_staple: !it.is_staple }, it.is_staple ? 'Снова учитываем остаток' : 'Теперь базовый')">
        {{ it.is_staple ? "Учитывать остаток" : "Сделать базовым" }}</button>
      <button v-if="it.is_staple" class="small" :disabled="busy" @click="flags({ is_low: !it.is_low }, it.is_low ? 'Отметка снята' : 'Добавится в покупки')">
        {{ it.is_low ? "Хватает" : "Заканчивается" }}</button>
      <span class="tiny muted">Базовые (соль, масло, специи) не считаются по граммам — в покупки попадают по отметке «заканчивается».</span>
    </div>

    <div v-if="!it.is_staple" class="box">
      <h3>Обычно берём</h3>
      <div class="row">
        <button v-for="o in REGULAR" :key="o.key" class="chip" :class="{ on: it.regular === o.key }" :aria-pressed="it.regular === o.key"
                :disabled="busy" @click="flags({ regular: o.key }, o.msg)">{{ o.label }}</button>
      </div>
      <div class="row">
        <span class="small">В неделю</span>
        <input v-model="regQty" type="number" min="0" step="any" inputmode="decimal" class="n3" placeholder="как обычно" aria-label="Сколько в неделю">
        <span class="small muted">{{ UNIT_LABEL[it.unit] }}</span>
        <button class="small" :disabled="busy || !regChanged" @click="flags({ regular_qty: regQty === '' ? null : num(regQty) }, 'Количество сохранено')">Сохранить</button>
      </div>
      <label class="check small"><input type="checkbox" :checked="!!it.is_snack" :disabled="busy" @change="onSnack"> Снек или сладкое — считать в квоту</label>
      <span class="tiny muted">«Как обычно» — по покупкам: брали в 4 из 8 последних недель — предложим в «Покупках». Пусто в «В неделю» — медиана покупок.</span>
    </div>

    <details v-if="history.length">
      <summary class="small">История ({{ history.length }})</summary>
      <div class="hist">
        <div v-for="m in history" :key="m.id" class="hrow small">
          <span>{{ dateTime(m.created_at) }} · {{ REASON[m.reason] || m.reason }}<span v-if="m.note" class="muted"> · {{ m.note }}</span></span>
          <b :class="num(m.delta) < 0 ? 'minus' : 'plus'">{{ num(m.delta) > 0 ? "+" : "" }}{{ fmtQty(m.delta, it.unit) }}</b>
        </div>
      </div>
    </details>

    <SplitLotModal v-if="splitting" :lot="splitting" :unit="it.unit" @close="splitting = null" @saved="onSplit" />
  </ModalSheet>
</template>

<style scoped>
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.grow { flex: 1; min-width: 0; }
.badge { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); }
.badge.warn { background: var(--beak-soft); color: var(--cook); }
.badge.danger { background: var(--beak-soft); color: var(--tomato); }
.lots { border: 1.5px solid var(--line); border-radius: var(--r-in); overflow: hidden; }
.lot { display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 12px; }
.lot + .lot { border-top: 1px solid var(--line); }
.ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.expired { color: var(--tomato); }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 600px) { .grid2 { grid-template-columns: 1fr; } }
.box { background: var(--enamel-2); border-radius: var(--r-in); padding: 12px; display: flex; flex-direction: column; gap: 8px; }
h3 { font-size: 15px; }
.n3 { width: 100px; }
button.small { min-height: 40px; padding: 0 12px; font-size: 14px; }
.danger { color: var(--tomato); border-color: var(--tomato); }
.chip { min-height: 40px; padding: 0 14px; border-color: var(--line); color: var(--ink); font-weight: 500; font-size: 14px; }
.chip.on { background: var(--rim); border-color: var(--rim); color: var(--on-fill); font-weight: 700; }
.check { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.check input { width: 20px; height: 20px; min-height: 0; accent-color: var(--rim); }
summary { cursor: pointer; color: var(--muted); }
.hist { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; }
.hrow { display: flex; justify-content: space-between; gap: 10px; }
.minus { color: var(--tomato); }
.plus { color: var(--rim); }
</style>
