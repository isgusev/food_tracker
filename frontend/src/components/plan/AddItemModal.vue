<script setup lang="ts">
// «Добавить в план»: блюдо (рецепт) или готовый продукт (поиск: справочник → штрихкод → Open Food Facts → вручную),
// порции по людям («как в прошлый раз» → типичные с сервера → стандартная порция), упаковки, гости, несколько дней.
import { computed, ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, recipeById, recipeCategoryName, variantIndex } from "../../catalog";
import { activeVariantOf, draftError, saveDraft, type Draft } from "../../drafts";
import { portionMemoryKey } from "../../plan";
import { activeMembers, toast } from "../../session";
import { MEALS, bjuLine, dayMonthShort, fmt, fmtQty, grams, local, num, packageGrams, weekdayShort } from "../../util";
import ItemPicker, { type PickerItem } from "../ItemPicker.vue";
import ModalSheet from "../ModalSheet.vue";
import BatchHint from "./BatchHint.vue";
import OffDraftCard from "../finder/OffDraftCard.vue";
import ProductFinder from "../finder/ProductFinder.vue";

const props = defineProps<{ date: string; meal: string; days?: string[] }>();
const emit = defineEmits<{ close: []; saved: [] }>();

type Row = { member_id: number; name: string; on: boolean; weight: number };
type Memory = { members?: Record<string, number>; guests?: number; guestWeight?: number; mode?: string; pkgIdx?: number; pkgCount?: number; pkgSplit?: string };

const kind = ref<"recipe" | "product">("recipe");
const recipeId = ref<number | null>(null);
const variantId = ref<number | null>(null);
const draft = ref<Draft | null>(null);
const exact = ref(false);
const meal = ref(props.meal || "lunch");
const dates = ref<string[]>([props.date]);
const rows = ref<Row[]>(activeMembers.value.map((m) => ({ member_id: m.id, name: m.name, on: true, weight: 250 })));
const guests = ref(0);
const guestWeight = ref(250);
const potStatus = ref<Schemas["PotSourceStatus"] | null>(null);
const busy = ref(false);
const error = ref("");

const recipeItems = computed<PickerItem[]>(() => [...catalog.recipes].map((r) => ({
  id: r.id, label: r.name, group: recipeCategoryName.value[r.recipe_category_id] || "Без категории",
  right: `${fmt(r.calories_per_100g)} ккал/100 г`,
  right2: bjuLine({ proteins: r.proteins_per_100g, fats: r.fats_per_100g, carbs: r.carbs_per_100g }),
})).sort((a, b) => a.group!.localeCompare(b.group!, "ru") || a.label.localeCompare(b.label, "ru")));
const recipe = computed(() => (recipeId.value ? recipeById.value[recipeId.value] : undefined));
const portionHint = computed(() => (recipe.value ? num(recipe.value.estimated_cooked_weight) / Math.max(1, recipe.value.default_servings || 1) : null));
const per100 = computed(() => {
  if (kind.value === "recipe" && recipe.value) {
    const r = recipe.value;
    return { calories: num(r.calories_per_100g) };
  }
  if (draft.value) return draft.value.kbju.calories === "" ? null : { calories: num(draft.value.kbju.calories) };
  const v = variantId.value ? variantIndex.value[variantId.value] : undefined;
  return v ? { calories: v.calories } : null;
});

// Упаковки готового продукта: можно сразу «по упаковке», а не граммами
const packages = computed(() => {
  if (kind.value !== "product") return [];
  if (draft.value) {
    const d = draft.value;
    return num(d.package_amount) > 0 && d.package_unit !== "pcs" ? [{ label: fmtQty(d.package_amount, d.package_unit || "g"), grams: num(d.package_amount) }] : [];
  }
  const p = variantId.value ? variantIndex.value[variantId.value]?.product : undefined;
  if (!p) return [];
  return (p.packages || []).map((pk) => ({ label: fmtQty(pk.amount, p.base_unit || "g"), grams: packageGrams(pk.amount, p.base_unit || "g", p.piece_weight_g) }))
    .filter((pk) => pk.grams > 0);
});
const amountMode = ref<"manual" | "package">("manual");
const pkgIdx = ref(0);
const pkgCount = ref(1);
const pkgSplit = ref<"each" | "shared">("each");
const pkg = computed(() => packages.value[pkgIdx.value] || packages.value[0] || null);
const byPackage = computed(() => packages.value.length > 0 && amountMode.value === "package");
function applyPackage() {
  if (!byPackage.value || !pkg.value) return;
  const g = pkg.value.grams * Math.max(1, num(pkgCount.value));
  const eaters = rows.value.filter((r) => r.on).length + num(guests.value);
  const w = Math.round((pkgSplit.value === "each" ? g : g / Math.max(1, eaters)) * 10) / 10;
  for (const r of rows.value) r.weight = w;
  guestWeight.value = w;
}
watch([amountMode, pkgIdx, pkgCount, pkgSplit, guests, () => rows.value.map((r) => r.on).join()], applyPackage);
const kcal = (w: number) => (per100.value ? (per100.value.calories * num(w)) / 100 : 0);
const total = computed(() => rows.value.filter((r) => r.on).reduce((s, r) => s + num(r.weight), 0) + num(guests.value) * num(guestWeight.value));

// Порции по умолчанию: «как в прошлый раз» для этого блюда, иначе типичные с сервера / стандартная порция
function applyDefaults(memoryKey: string | null, fallback: number): Memory | null {
  const saved = memoryKey ? local.get<Memory | null>(memoryKey, null) : null;
  for (const r of rows.value) {
    const w = saved?.members?.[String(r.member_id)];
    r.on = saved ? w != null : true;
    r.weight = Math.round(w ?? fallback);
  }
  guests.value = saved?.guests || 0;
  guestWeight.value = Math.round(saved?.guestWeight || fallback);
  return saved;
}
async function typicalDefaults(id: number) {
  try {
    const t = await ok(api.GET("/api/v1/plan/typical-portions", { params: { query: { meal_type: meal.value, recipe_id: id } } }));
    if (recipeId.value !== id) return;      // рецепт уже сменили — ответ устарел
    const by = Object.fromEntries(t.map((x) => [x.member_id, num(x.weight_g)]));
    for (const r of rows.value) if (by[r.member_id] != null) r.weight = by[r.member_id];
  } catch { /* подсказка необязательна */ }
}
watch(recipeId, (id) => {
  if (!id) return;
  if (!applyDefaults(portionMemoryKey("r", id), portionHint.value || 250)) typicalDefaults(id);
});
function productDefaults(memoryKey: string | null) {
  const saved = applyDefaults(memoryKey, 100);
  pkgIdx.value = Math.min(saved?.pkgIdx || 0, Math.max(0, packages.value.length - 1));
  pkgCount.value = saved?.pkgCount || 1;
  pkgSplit.value = saved?.pkgSplit === "shared" ? "shared" : "each";
  amountMode.value = packages.value.length && (!saved || saved.mode === "package") ? "package" : "manual";
  applyPackage();
}
watch(variantId, (id) => { if (id) productDefaults(portionMemoryKey("v", id)); });
watch(draft, (d, old) => { if (d && !old) productDefaults(null); });

// Подсказка кастрюли: есть ли это блюдо в холодильнике и хватит ли свободного
watch([recipeId, total, kind], async () => {
  potStatus.value = null;
  if (kind.value !== "recipe" || !recipeId.value || !(total.value > 0)) return;
  try {
    potStatus.value = await ok(api.GET("/api/v1/plan/pot-status/{recipe_id}", {
      params: { path: { recipe_id: recipeId.value }, query: { portion_g: total.value } } }));
  } catch { /* подсказка необязательна */ }
});
const potFree = computed(() => (potStatus.value ? num(potStatus.value.available_g) - num(potStatus.value.planned_g) : 0));

// «Разделить всю закладку»: порции (и гостей) — пропорционально под target граммов
function fitTo(target: number) {
  const k = total.value > 0 ? target / total.value : 1;
  for (const r of rows.value) if (r.on) r.weight = Math.round(num(r.weight) * k);
  if (num(guests.value)) guestWeight.value = Math.round(num(guestWeight.value) * k);
}

function toggleDate(d: string) {
  const i = dates.value.indexOf(d);
  if (i >= 0) { if (dates.value.length > 1) dates.value.splice(i, 1); } else dates.value.push(d);
}

async function save() {
  error.value = "";
  const portions: { member_id: number | null; weight_g: number }[] = rows.value.filter((r) => r.on && num(r.weight) > 0)
    .map((r) => ({ member_id: r.member_id, weight_g: num(r.weight) }));
  for (let i = 0; i < num(guests.value); i++) portions.push({ member_id: null, weight_g: num(guestWeight.value) });
  let recipe_id: number | null = null;
  let variant_id: number | null = null;
  if (kind.value === "recipe") {
    if (!recipeId.value) { error.value = "Выберите блюдо"; return; }
    recipe_id = recipeId.value;
  } else {
    if (!variantId.value && !draft.value) { error.value = "Выберите продукт"; return; }
    if (variantId.value && variantIndex.value[variantId.value]?.kbjuMissing) { error.value = "Сначала внесите КБЖУ продукта — поля выше"; return; }
    if (draft.value && (error.value = draftError(draft.value))) return;
    variant_id = variantId.value;
  }
  if (!portions.length) { error.value = "Отметьте, кто ест"; return; }
  busy.value = true;
  try {
    if (kind.value === "product" && draft.value) {
      // продукт из Open Food Facts или введённый вручную — сначала в справочник, потом в план
      const product = await saveDraft(draft.value);
      variant_id = activeVariantOf(product, draft.value.manufacturer || draft.value.brand);
      if (!variant_id) throw new Error("У сохранённого продукта нет активной версии КБЖУ");
    }
    for (const d of [...dates.value].sort()) {
      await ok(api.POST("/api/v1/plan", { body: {
        date_day: d, meal_type: meal.value, portions,
        ...(recipe_id ? { recipe_id } : { variant_id, exact: exact.value }),
      } }));
    }
    local.set(portionMemoryKey(kind.value === "recipe" ? "r" : "v", (recipe_id || variant_id)!), {
      members: Object.fromEntries(rows.value.filter((r) => r.on).map((r) => [r.member_id, num(r.weight)])),
      guests: num(guests.value), guestWeight: num(guestWeight.value),
      mode: amountMode.value, pkgIdx: pkgIdx.value, pkgCount: num(pkgCount.value), pkgSplit: pkgSplit.value,
    });
    toast(dates.value.length > 1 ? `Добавлено в ${dates.value.length} дн.` : "Добавлено в план");
    emit("saved");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <ModalSheet title="Добавить в план" @close="emit('close')">
    <div class="seg" role="group" aria-label="Что добавить">
      <button :class="{ on: kind === 'recipe' }" :aria-pressed="kind === 'recipe'" @click="kind = 'recipe'">Блюдо</button>
      <button :class="{ on: kind === 'product' }" :aria-pressed="kind === 'product'" @click="kind = 'product'">Готовый продукт</button>
    </div>

    <div v-if="kind === 'recipe'" class="field">
      <span class="lbl">Блюдо</span>
      <ItemPicker v-model="recipeId as number | null" :items="recipeItems" placeholder="Поиск по рецептам…" autofocus />
      <span v-if="!recipeItems.length" class="tiny muted">Рецептов пока нет — создайте их в разделе «Рецепты».</span>
      <span v-else-if="portionHint" class="tiny muted">Стандартная порция ≈ {{ fmt(portionHint) }} г</span>
    </div>
    <div v-else class="field">
      <span class="lbl">Продукт из магазина</span>
      <ProductFinder v-model="variantId" v-model:draft="draft" autofocus kbju-prompt />
      <span v-if="!variantId && !draft" class="tiny muted">Сначала ищем в справочнике, не нашли — в Open Food Facts. 📷 — штрихкод камерой.</span>
    </div>
    <OffDraftCard v-if="kind === 'product' && draft" v-model="draft" />
    <label v-if="kind === 'product' && (variantId || draft)" class="check small">
      <input v-model="exact" type="checkbox">
      <span>🎯 Именно этот вариант <span class="muted">— в покупках этот бренд, а не любой бренд того же товара</span></span>
    </label>

    <div v-if="packages.length" class="field">
      <div class="seg" role="group" aria-label="Как задать количество">
        <button :class="{ on: amountMode === 'package' }" @click="amountMode = 'package'">По упаковке</button>
        <button :class="{ on: amountMode === 'manual' }" @click="amountMode = 'manual'">Вес вручную</button>
      </div>
      <div v-if="amountMode === 'package'" class="row">
        <input v-model.number="pkgCount" type="number" min="1" step="1" class="n2" aria-label="Сколько упаковок">
        <span class="muted">×</span>
        <select v-if="packages.length > 1" v-model.number="pkgIdx" class="auto" aria-label="Упаковка">
          <option v-for="(p, i) in packages" :key="i" :value="i">{{ p.label }}</option>
        </select>
        <b v-else>{{ packages[0].label }}</b>
        <div class="seg">
          <button :class="{ on: pkgSplit === 'each' }" @click="pkgSplit = 'each'">каждому</button>
          <button :class="{ on: pkgSplit === 'shared' }" @click="pkgSplit = 'shared'">на всех</button>
        </div>
      </div>
    </div>

    <div class="field">
      <div class="row between"><span class="lbl">Кто ест и сколько, г</span><span class="small muted">всего {{ grams(total) }}</span></div>
      <div v-for="r in rows" :key="r.member_id" class="eater">
        <label class="check grow"><input v-model="r.on" type="checkbox"><span>{{ r.name }}</span></label>
        <input v-model.number="r.weight" type="number" min="1" max="2000" step="any" class="n3" inputmode="decimal"
               :aria-label="'Порция, г: ' + r.name" :disabled="!r.on || byPackage">
        <span class="kc small muted">{{ r.on && per100 ? fmt(kcal(r.weight)) + " ккал" : "" }}</span>
      </div>
      <div class="eater">
        <span class="grow small">Гости</span>
        <select v-model.number="guests" class="n2" aria-label="Сколько гостей"><option v-for="i in 11" :key="i" :value="i - 1">{{ i - 1 }}</option></select>
        <span class="small muted">по</span>
        <input v-model.number="guestWeight" type="number" min="1" max="2000" step="any" class="n3" aria-label="Порция гостя, г" :disabled="!guests || byPackage">
        <span class="kc"></span>
      </div>
      <span class="tiny muted">Гости учитываются в кастрюле и покупках, но не в чьих-то КБЖУ.</span>
    </div>

    <div v-if="potStatus && potStatus.has_active_pot" class="note" :class="potFree >= total ? 'ok' : 'warn'">
      В холодильнике есть это блюдо: осталось {{ grams(potStatus.available_g) }}, из них запланировано {{ grams(potStatus.planned_g) }}.
      <template v-if="potFree >= total">Свободного хватает — возьмём из кастрюли.</template>
      <template v-else>Свободно только {{ grams(Math.max(0, potFree)) }} — блюдо попадёт в покупки как «надо приготовить».</template>
    </div>

    <BatchHint v-if="kind === 'recipe' && dates.length === 1 && !(potStatus?.has_active_pot && potFree >= total)"
               :recipe-id="recipeId" :date="dates[0]" :weight="total" :disabled="busy" @fit="fitTo" />

    <div class="field">
      <span class="lbl">Приём пищи</span>
      <div class="seg wrap"><button v-for="m in MEALS" :key="m.key" :class="{ on: meal === m.key }" @click="meal = m.key">{{ m.label }}</button></div>
    </div>
    <div v-if="days && days.length" class="field">
      <span class="lbl">Дни — можно несколько</span>
      <div class="seg wrap">
        <button v-for="d in days" :key="d" :class="{ on: dates.includes(d) }" :aria-pressed="dates.includes(d)" @click="toggleDate(d)">
          {{ weekdayShort(d) }} {{ dayMonthShort(d) }}</button>
      </div>
    </div>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy" @click="save">{{ busy ? "Добавляю…" : "Добавить" }}</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.between { justify-content: space-between; }
.seg { display: inline-flex; flex-wrap: nowrap; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); align-self: flex-start; }
.seg.wrap { flex-wrap: wrap; border-radius: var(--r-in); }
.seg button { min-height: 38px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
.check { display: flex; align-items: center; gap: 10px; cursor: pointer; }
.check input { width: 20px; height: 20px; min-height: 0; accent-color: var(--rim); }
.eater { display: flex; align-items: center; gap: 8px; }
.grow { flex: 1; min-width: 0; }
.n2 { width: 70px; }
.n3 { width: 92px; }
.auto { width: auto; }
.kc { width: 76px; text-align: right; flex: none; }
.note { padding: 10px 12px; border-radius: var(--r-in); font-size: 14px; }
.note.ok { background: var(--rim-soft); }
.note.warn { background: var(--beak-soft); }
.err { color: var(--tomato); margin: 0; }
</style>
