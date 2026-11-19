<script setup lang="ts">
// «Холодильник → Продукты»: запасы по товарам (все бренды вместе), группы по категориям, поиск,
// бейджи (базовый / заканчивается / учёт сбился), ближайший срок и просрочка. Сам по себе: без пропсов
// и событий; родитель пересоздаёт его через :key после готовки или правки кастрюли.
import { computed, onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { ensureCatalog } from "../../catalog";
import { toastError } from "../../session";
import { dayMonthShort, fmtQty, matches, num } from "../../util";
import AddLotModal from "./AddLotModal.vue";
import QuickInventory from "./QuickInventory.vue";
import StockItemModal from "./StockItemModal.vue";

type StockItem = Schemas["StockItem"];

const items = ref<StockItem[]>([]);
const loaded = ref(false);
const q = ref("");
const adding = ref(false);
const opened = ref<StockItem | null>(null);
const quick = ref(false);

async function load() {
  try { await ensureCatalog(); items.value = await ok(api.GET("/api/v1/stock")); }
  catch (e) { toastError(e); } finally { loaded.value = true; }
}
onMounted(load);

const groups = computed(() => {
  const map = new Map<string, StockItem[]>();
  for (const i of items.value.filter((x) => matches(x.name, q.value))) {
    const g = i.category_name || "Без категории";
    if (!map.has(g)) map.set(g, []);
    map.get(g)!.push(i);
  }
  return [...map.entries()].map(([name, list]) => ({ name, list }));
});
const checks = computed(() => items.value.filter((i) => i.needs_check).length);

/** Мутации запасов отвечают полным списком — он подменяет экран; нет списка — перечитываем. */
function onSaved(list: StockItem[] | null) {
  if (Array.isArray(list)) items.value = list; else load();
  adding.value = false;
  quick.value = false;
}
function onItemSaved(list: StockItem[]) { items.value = list; }
</script>

<template>
  <div class="stock">
    <div class="tools">
      <input v-model="q" type="search" class="search" placeholder="Поиск…" aria-label="Поиск по запасам">
      <button class="fill" @click="adding = true">+ Добавить</button>
      <button :disabled="!items.length" @click="quick = true">Инвентаризация</button>
      <span v-if="checks" class="badge warn">учёт сбился: {{ checks }}</span>
    </div>

    <p v-if="loaded && !items.length" class="empty">Запасов пока нет. Они появятся, когда отметите покупки в списке, или добавьте вручную.</p>
    <p v-else-if="loaded && !groups.length" class="empty">Ничего не найдено.</p>
    <div v-else class="list">
      <section v-for="g in groups" :key="g.name">
        <h3 class="cat">{{ g.name }}</h3>
        <button v-for="i in g.list" :key="i.item_key" class="item" @click="opened = i">
          <span class="grow">
            <span class="name">{{ i.name }}</span>
            <span v-if="i.is_staple" class="badge">базовый</span>
            <span v-if="i.is_low" class="badge warn">заканчивается</span>
            <span v-if="i.needs_check" class="badge warn">учёт сбился</span>
            <span v-if="i.nearest_expiry" class="tiny muted when">годен до {{ dayMonthShort(i.nearest_expiry) }}<span v-if="num(i.expired) > 0" class="expired"> · просрочено {{ fmtQty(i.expired, i.unit) }}</span></span>
          </span>
          <b v-if="!i.is_staple" class="qty">{{ fmtQty(i.remaining, i.unit) }}</b>
        </button>
      </section>
    </div>

    <AddLotModal v-if="adding" @close="adding = false" @saved="onSaved" />
    <StockItemModal v-if="opened" :item="opened" @close="opened = null" @saved="onItemSaved" />
    <QuickInventory v-if="quick" :items="items" @close="quick = false" @saved="onSaved" />
  </div>
</template>

<style scoped>
.stock { display: flex; flex-direction: column; gap: 12px; }
.tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.search { max-width: 260px; }
.empty { margin: 0; padding: 24px; text-align: center; color: var(--muted); background: var(--enamel); border: 1.5px solid var(--line); border-radius: var(--r-pot); }
.list { background: var(--enamel); border: 1.5px solid var(--line); border-radius: var(--r-pot); overflow: hidden; }
.cat { font-size: 13px; font-weight: 600; color: var(--muted); padding: 10px 16px 6px; background: var(--enamel-2); }
.item {
  width: 100%; min-height: 52px; display: flex; align-items: center; gap: 12px; padding: 10px 16px; text-align: left;
  border: 0; border-top: 1px solid var(--line); border-radius: 0; background: transparent; color: var(--ink); font-weight: 400;
}
section .item:first-of-type { border-top: 0; }
.item:hover { background: var(--rim-soft); }
.grow { flex: 1; min-width: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; }
.name { font-weight: 600; }
.when { flex-basis: 100%; }
.expired { color: var(--tomato); }
.qty { white-space: nowrap; }
.badge { font-size: 12px; padding: 2px 10px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); font-weight: 500; }
.badge.warn { background: var(--beak-soft); color: var(--cook); }
</style>
