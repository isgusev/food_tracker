<script setup lang="ts">
// Справочник: продукты (поиск по названию, бренду, штрихкоду; категории) и товары (объединение без брендов).
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import type { Schemas } from "../../api/client";
import { catalog, categoryName, ensureCatalog } from "../../catalog";
import NewProductModal from "../../components/catalog/NewProductModal.vue";
import ProductModal from "../../components/catalog/ProductModal.vue";
import { toast, toastError } from "../../session";
import { fmt, fmtMacro, fuzzyScore, local, matches, packagesLabel } from "../../util";

const ItemsPanel = defineAsyncComponent(() => import("../../components/catalog/ItemsPanel.vue"));
type Product = Schemas["ProductResponse"];
const PAGE = 120;   // длинный справочник — частями, чтобы список открывался мгновенно

const tab = ref<"products" | "items">(local.get("ft.catalogTab", "products"));
watch(tab, (t) => local.set("ft.catalogTab", t));
const q = ref("");
const cat = ref(0);
const shown = ref(PAGE);
watch([q, cat], () => { shown.value = PAGE; });
const creating = ref(false);
const opened = ref<Product | null>(null);
onMounted(() => ensureCatalog().catch(toastError));

const cats = computed(() => {
  const count = new Map<number, number>();
  for (const p of catalog.products) count.set(p.category_id, (count.get(p.category_id) ?? 0) + 1);
  return catalog.productCategories.filter((c) => count.has(c.id)).map((c) => ({ ...c, n: count.get(c.id)! }))
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
});
const rows = computed(() => catalog.products
  .filter((p) => (!cat.value || p.category_id === cat.value)
    && (matches(`${p.name} ${p.brand?.name || ""} ${p.barcode || ""}`, q.value) || fuzzyScore(q.value, `${p.name} ${p.brand?.name || ""}`) >= 0.6))
  .map((p) => {
    const actives = (p.manufacturers ?? []).flatMap((m) => (m.variants ?? []).filter((v) => v.is_active));
    const brand = p.brand?.name && p.brand.name !== "Без бренда" ? p.brand.name : "";
    return { p, v: actives[0], brand, makers: (p.manufacturers ?? []).length, warn: actives.some((x) => x.wrong_nutrients) };
  })
  .sort((a, b) => (q.value ? fuzzyScore(q.value, `${b.p.name} ${b.brand}`) - fuzzyScore(q.value, `${a.p.name} ${a.brand}`) : 0)
    || (categoryName.value[a.p.category_id] || "").localeCompare(categoryName.value[b.p.category_id] || "", "ru")
    || a.p.name.localeCompare(b.p.name, "ru")));
// заголовки категорий — только без поиска (с поиском порядок по похожести)
const withHeads = computed(() => rows.value.slice(0, shown.value).map((r, i, arr) => ({
  ...r, head: !q.value && !cat.value && (i === 0 || arr[i - 1].p.category_id !== r.p.category_id) ? categoryName.value[r.p.category_id] || "Без категории" : "",
})));
function openExisting(p: Product) { creating.value = false; opened.value = p; toast("Этот продукт уже есть в справочнике"); }
</script>

<template>
  <div class="catalog">
    <header class="head">
      <h1 class="display">Продукты</h1>
      <button class="fill" @click="creating = true">+ Продукт</button>
    </header>
    <div class="tabs" role="tablist">
      <button role="tab" :aria-selected="tab === 'products'" :class="{ on: tab === 'products' }" @click="tab = 'products'">Продукты · {{ catalog.products.length }}</button>
      <button role="tab" :aria-selected="tab === 'items'" :class="{ on: tab === 'items' }" @click="tab = 'items'">Товары</button>
    </div>

    <ItemsPanel v-if="tab === 'items'" />
    <template v-else>
      <div class="tools">
        <span class="search">
          <input v-model="q" type="search" placeholder="Название, бренд или штрихкод…" aria-label="Поиск продукта">
          <button v-if="q" class="text clear" aria-label="Очистить" @click="q = ''">✕</button>
        </span>
        <select v-model.number="cat" class="cat" aria-label="Категория">
          <option :value="0">Все категории</option>
          <option v-for="c in cats" :key="c.id" :value="c.id">{{ c.name }} · {{ c.n }}</option>
        </select>
      </div>
      <p v-if="q || cat" class="small muted">Найдено: {{ rows.length }}</p>

      <div class="list">
        <template v-for="r in withHeads" :key="r.p.id">
          <h2 v-if="r.head" class="cat-h">{{ r.head }}</h2>
          <button class="row" @click="opened = r.p">
            <span class="what">
              <span class="name">{{ r.p.name }}
                <span v-if="r.warn" class="flag" title="Калории не сходятся с БЖУ">⚠</span>
                <span v-if="r.p.kbju_missing" class="flag" title="Добавлен из чека или покупок — внесите КБЖУ">нет КБЖУ</span></span>
              <span class="tiny muted">
                <template v-if="r.p.item && r.p.item.name !== r.p.name">{{ r.p.item.name }} · </template>{{ r.brand || "без бренда" }}<template v-if="r.makers > 1"> · {{ r.makers }} произв.</template>
                · {{ packagesLabel(r.p.packages, r.p.base_unit || "g") }}<template v-if="q || cat"> · {{ categoryName[r.p.category_id] }}</template></span>
            </span>
            <span v-if="r.v && !r.p.kbju_missing" class="kb">
              <span><b>{{ fmt(r.v.calories) }}</b><span class="tiny muted"> ккал</span></span>
              <span class="tiny muted bju">Б {{ fmtMacro(r.v.proteins) }} · Ж {{ fmtMacro(r.v.fats) }} · У {{ fmtMacro(r.v.carbs) }}</span>
            </span>
          </button>
        </template>
        <p v-if="catalog.loaded.products && !rows.length" class="muted pad">Ничего не найдено — «+ Продукт» поищет и в Open Food Facts.</p>
      </div>
      <button v-if="rows.length > shown" class="more" @click="shown += PAGE">Показать ещё {{ Math.min(PAGE, rows.length - shown) }} из {{ rows.length - shown }}</button>
      <p class="tiny muted">КБЖУ — на 100 г, по активной версии.</p>
    </template>

    <NewProductModal v-if="creating" @close="creating = false" @saved="creating = false" @open="openExisting" />
    <ProductModal v-if="opened" :product="opened" @close="opened = null" />
  </div>
</template>

<style scoped>
.catalog { display: flex; flex-direction: column; gap: 14px; max-width: 900px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
h1 { font-size: 32px; color: var(--rim); }
p { margin: 0; }
.tabs { display: inline-flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); align-self: flex-start; }
.tabs button { min-height: 40px; border: 0; padding: 0 16px; color: var(--ink); font-weight: 500; }
.tabs button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
.tools { display: flex; flex-wrap: wrap; gap: 8px; }
.search { position: relative; flex: 1 1 260px; max-width: 420px; }
.search input { padding-right: 44px; }
.search input::-webkit-search-cancel-button { display: none; }
.clear { position: absolute; right: 0; top: 0; min-width: 44px; padding: 0; color: var(--muted); }
.cat { flex: 0 1 240px; width: auto; }
.list { border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); overflow: hidden; }
.cat-h { font-size: 14px; font-weight: 600; color: var(--muted); padding: 12px 16px 2px; border-top: 1px solid var(--line); }
.cat-h:first-child { border-top: 0; }
.row { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 56px; padding: 8px 16px; border: 0; border-radius: 0;
  border-top: 1px solid var(--line); background: transparent; color: var(--ink); font-weight: 400; text-align: left; }
.cat-h + .row, .row:first-child { border-top: 0; }
.row:hover { background: var(--rim-soft); }
.what { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.name { overflow-wrap: anywhere; }
.flag { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--beak-soft); color: var(--cook); font-weight: 600; white-space: nowrap; }
.kb { display: flex; flex-direction: column; align-items: flex-end; text-align: right; white-space: nowrap; }
.kb b { font-size: 16px; }
.pad { padding: 14px 16px; }
.more { align-self: center; }
@media (max-width: 600px) { .bju { display: none; } }
</style>
