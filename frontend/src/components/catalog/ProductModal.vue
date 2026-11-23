<script setup lang="ts">
// Карточка продукта справочника: штрихкод, единица учёта и упаковки (общие для товара), версии КБЖУ по производителям
// (новая версия, другой производитель, откат). Каждое действие сразу сохраняется и перечитывает справочник.
import { computed, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, categoryName, loadProducts } from "../../catalog";
import { CODE_RE, type Kbju } from "../../drafts";
import { toast } from "../../session";
import { UNIT_LABEL, fmt, fmtQty, num } from "../../util";
import ModalSheet from "../ModalSheet.vue";
import BarcodeScanner from "../finder/BarcodeScanner.vue";
import KbjuInputs from "../finder/KbjuInputs.vue";

type Product = Schemas["ProductResponse"];
type Maker = Schemas["ManufacturerResponse"];
const props = defineProps<{ product: Product }>();
const emit = defineEmits<{ close: [] }>();

// всегда свежая версия из справочника (после каждого сохранения он перечитывается)
const p = computed(() => catalog.products.find((x) => x.id === props.product.id) || props.product);
const busy = ref(false);
const error = ref("");
async function run(fn: () => Promise<unknown>, msg: string) {
  error.value = "";
  busy.value = true;
  try { await fn(); await loadProducts(); toast(msg); return true; }
  catch (e) { error.value = (e as Error).message; return false; }
  finally { busy.value = false; }
}
const pid = () => ({ product_id: p.value.id });

// ---- штрихкод: чтобы в следующий раз найти продукт сканером
const code = ref(p.value.barcode || "");
const scanning = ref(false);
const validCode = computed(() => CODE_RE.test(code.value));
const saveCode = () => validCode.value && run(() => ok(api.PUT("/api/v1/products/{product_id}/barcode", { params: { path: pid() }, body: { barcode: code.value } })), "Штрихкод сохранён");
function onScan(c: string) { scanning.value = false; code.value = c; saveCode(); }

// ---- единица учёта и упаковки
const unit = ref(p.value.base_unit || "g");
const piece = ref<number | string>(p.value.piece_weight_g != null ? num(p.value.piece_weight_g) : "");
const unitChanged = computed(() => unit.value !== (p.value.base_unit || "g")
  || (unit.value === "pcs" && num(piece.value) !== num(p.value.piece_weight_g)));
const saveUnit = () => run(() => ok(api.PUT("/api/v1/products/{product_id}/unit", { params: { path: pid() },
  body: { base_unit: unit.value, piece_weight_g: unit.value === "pcs" ? num(piece.value) || null : null } })), "Единица сохранена — для всех брендов этого товара");
const pkgAmount = ref<number | string>("");
const pkgName = ref("");
async function addPkg() {
  if (!(num(pkgAmount.value) > 0)) return;
  if (await run(() => ok(api.POST("/api/v1/products/{product_id}/packages", { params: { path: pid() }, body: { amount: num(pkgAmount.value), name: pkgName.value.trim() || null } })), "Упаковка добавлена")) {
    pkgAmount.value = ""; pkgName.value = "";
  }
}
const delPkg = (id: number) => run(async () => {
  const r = await api.DELETE("/api/v1/products/packages/{package_id}", { params: { path: { package_id: id } } });
  if (!r.response.ok) await ok(Promise.resolve(r));
}, "Упаковка удалена");

// ---- версии КБЖУ
const adding = ref<{ makerId: number | null; name: string; kbju: Kbju } | null>(null);
function startAdd(m: Maker | null) {
  const a = m?.variants?.find((v) => v.is_active);
  adding.value = { makerId: m?.id ?? null, name: m ? m.name || "" : "",
    kbju: { calories: a ? num(a.calories) : "", proteins: a ? num(a.proteins) : "", fats: a ? num(a.fats) : "", carbs: a ? num(a.carbs) : "" } };
}
async function saveVariant() {
  const a = adding.value!;
  if (Object.values(a.kbju).some((v) => v === "" || v == null)) { error.value = "Заполните КБЖУ на 100 г — с упаковки"; return; }
  if (await run(() => ok(api.POST("/api/v1/products/{product_id}/variants", { params: { path: pid() }, body: {
    manufacturer_name: a.name.trim() || null,
    calories: num(a.kbju.calories), proteins: num(a.kbju.proteins), fats: num(a.kbju.fats), carbs: num(a.kbju.carbs),
  } })), "Новая версия КБЖУ сохранена")) adding.value = null;
}
function rollback(m: Maker) {
  if (!confirm("Вернуть предыдущую версию КБЖУ этого производителя?")) return;
  run(() => ok(api.POST("/api/v1/products/{product_id}/manufacturers/{manufacturer_id}/rollback", { params: { path: { ...pid(), manufacturer_id: m.id } } })), "Откат выполнен");
}
const versions = (m: Maker) => [...(m.variants ?? [])].sort((a, b) => (b.version ?? 1) - (a.version ?? 1));
const activeVersion = (m: Maker) => m.variants?.find((v) => v.is_active)?.version ?? 1;
const brand = computed(() => (p.value.brand?.name && p.value.brand.name !== "Без бренда" ? p.value.brand.name : ""));
</script>

<template>
  <ModalSheet :title="p.name" wide @close="emit('close')">
    <div class="chips">
      <span class="chip">{{ categoryName[p.category_id] || "Без категории" }}</span>
      <span v-if="brand" class="chip">{{ brand }}</span>
      <span v-if="p.item && p.item.name !== p.name" class="chip" title="Товар — без бренда: так он считается в покупках и запасах">товар «{{ p.item.name }}»</span>
      <span v-if="p.kbju_missing" class="chip warn">нет КБЖУ</span>
    </div>
    <p v-if="p.kbju_missing" class="note small">Продукт добавлен из чека или покупок без КБЖУ — внесите цифры с упаковки: «Новые КБЖУ» ниже.</p>

    <section class="block">
      <h3>Штрихкод</h3>
      <div class="inline">
        <input v-model="code" inputmode="numeric" placeholder="не задан" aria-label="Штрихкод" class="code" @keydown.enter="saveCode">
        <button class="sq" title="Сканировать камерой" aria-label="Сканировать штрихкод" @click="scanning = true">📷</button>
        <button v-if="code !== (p.barcode || '')" class="small" :disabled="busy || !validCode" @click="saveCode">Сохранить</button>
      </div>
      <span v-if="code && !validCode" class="tiny muted">8–14 цифр</span>
    </section>

    <section class="block">
      <h3>Покупка и учёт запасов</h3>
      <div class="inline wrap">
        <div class="seg" role="radiogroup" aria-label="Единица учёта">
          <button v-for="u in ['g', 'ml', 'pcs']" :key="u" role="radio" :aria-checked="unit === u" :class="{ on: unit === u }" @click="unit = u">
            {{ { g: "граммы", ml: "мл", pcs: "штуки" }[u] }}</button>
        </div>
        <template v-if="unit === 'pcs'"><span class="small muted">1 шт =</span>
          <input v-model="piece" type="number" min="1" step="any" inputmode="decimal" class="num" aria-label="Вес одной штуки, г"><span class="small muted">г</span></template>
        <button v-if="unitChanged" class="small" :disabled="busy" @click="saveUnit">Сохранить</button>
      </div>
      <p class="tiny muted">Единица общая для всех брендов этого товара. Рецепты и КБЖУ — всегда в граммах; штуки пересчитываются по весу одной.</p>
      <div class="pkgs">
        <span class="small">Упаковки:</span>
        <span v-for="pk in p.packages" :key="pk.id" class="pkg">{{ fmtQty(pk.amount, p.base_unit || "g") }}<template v-if="pk.name"> · {{ pk.name }}</template>
          <button class="text x" :aria-label="'Удалить упаковку ' + fmt(pk.amount)" :disabled="busy" @click="delPkg(pk.id)">✕</button></span>
        <span v-if="!p.packages?.length" class="small muted">нет — покупки не округлятся до пачек</span>
      </div>
      <div class="inline wrap">
        <input v-model="pkgAmount" type="number" min="0.1" step="any" inputmode="decimal" :placeholder="'Сколько, ' + UNIT_LABEL[p.base_unit || 'g']" class="mid" aria-label="Размер упаковки" @keydown.enter="addPkg">
        <input v-model="pkgName" placeholder="Название (пачка…)" class="mid" aria-label="Название упаковки" @keydown.enter="addPkg">
        <button class="small" :disabled="busy || !(num(pkgAmount) > 0)" @click="addPkg">+ Упаковка</button>
      </div>
    </section>

    <section v-for="m in p.manufacturers" :key="m.id" class="block">
      <div class="mhead">
        <h3 class="grow">{{ m.name || "Без производителя" }}</h3>
        <button class="text small" :disabled="busy" @click="startAdd(m)">Новые КБЖУ</button>
        <button v-if="activeVersion(m) > 1" class="text small" :disabled="busy" @click="rollback(m)">↶ Откат</button>
      </div>
      <div class="vt">
        <div class="vrow head tiny muted"><span>Версия</span><span>ккал</span><span>Б</span><span>Ж</span><span>У</span></div>
        <div v-for="v in versions(m)" :key="v.id" class="vrow" :class="{ old: !v.is_active }">
          <span>v{{ v.version }} <span v-if="v.is_active" class="ok tiny">активна</span>
            <span v-if="v.wrong_nutrients" class="warn tiny" title="Калории не сходятся с БЖУ">⚠ проверить</span></span>
          <span>{{ fmt(v.calories, 1) }}</span><span>{{ fmt(v.proteins, 1) }}</span><span>{{ fmt(v.fats, 1) }}</span><span>{{ fmt(v.carbs, 1) }}</span>
        </div>
      </div>
    </section>

    <section v-if="adding" class="block edit">
      <h3>{{ adding.makerId == null ? "Другой производитель" : "Новая версия КБЖУ" }}</h3>
      <label v-if="adding.makerId == null" class="field"><span class="lbl">Производитель</span><input v-model="adding.name" autofocus></label>
      <KbjuInputs v-model="adding.kbju" />
      <p class="tiny muted">Рецепты с этим продуктом пересчитаются по новой версии. Приготовленное в холодильнике и съеденное останутся как были.</p>
      <div class="inline"><button class="fill small" :disabled="busy" @click="saveVariant">Сохранить</button>
        <button class="text small" @click="adding = null">Отмена</button></div>
    </section>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <BarcodeScanner v-if="scanning" @close="scanning = false" @code="onScan" />
    <template #foot>
      <button v-if="!adding" class="text" @click="startAdd(null)">+ Другой производитель</button>
      <span class="grow"></span>
      <button class="fill" @click="emit('close')">Готово</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
h3 { font-size: 16px; }
.grow { flex: 1; min-width: 0; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { font-size: 13px; padding: 3px 10px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); }
.chip.warn { background: var(--beak-soft); color: var(--cook); }
.note { padding: 10px 12px; border-radius: var(--r-in); background: var(--beak-soft); }
.block { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; border-radius: var(--r-in); border: 1.5px solid var(--line); }
.block.edit { border-color: var(--rim); }
.inline { display: flex; align-items: center; gap: 8px; }
.inline.wrap { flex-wrap: wrap; }
.code { max-width: 220px; }
.num { width: 88px; }
.mid { width: 170px; flex: 1 1 140px; }
.sq { width: 44px; padding: 0; flex: none; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
.seg { display: inline-flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); }
.seg button { min-height: 38px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
.pkgs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.pkg { display: inline-flex; align-items: center; gap: 2px; padding: 2px 4px 2px 12px; border-radius: 999px; background: var(--enamel-2); font-size: 14px; }
.x { min-height: 32px; min-width: 32px; padding: 0; color: var(--muted); }
.mhead { display: flex; align-items: center; gap: 4px; }
.vt { display: flex; flex-direction: column; }
.vrow { display: grid; grid-template-columns: 1fr repeat(4, 56px); gap: 6px; padding: 6px 0; border-top: 1px solid var(--line); font-size: 14px; }
.vrow > span:not(:first-child) { text-align: right; }
.vrow.head { border-top: 0; padding-top: 0; }
.vrow.old { color: var(--muted); }
.ok { color: var(--rim); font-weight: 600; }
.warn { color: var(--cook); font-weight: 600; }
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.err { color: var(--tomato); }
@media (max-width: 600px) { .vrow { grid-template-columns: 1fr repeat(4, 44px); } }
</style>
