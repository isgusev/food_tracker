<script setup lang="ts">
// «Продукты → Товары»: товар — продукт без бренда («Кефир 3,2%» любого производителя — одна строка в покупках и один
// остаток). Предложения объединить похожие (скрытые — на этом устройстве), переименование, перенос продукта.
import { computed, onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { loadProducts } from "../../catalog";
import { toast, toastError } from "../../session";
import { fmtQty, fuzzyScore, local } from "../../util";
import MoveModal from "./MoveModal.vue";

type Item = Schemas["ItemOut"];
type Group = Schemas["ItemSuggestion"] & { chosen: string[]; title: string };
const HIDDEN_KEY = "ft.itemSuggestionsHidden";
const groupId = (g: Schemas["ItemSuggestion"]) => g.items.map((i) => i.key).sort().join("|");

const items = ref<Item[]>([]);
const groups = ref<Group[]>([]);
const hidden = ref<string[]>(local.get(HIDDEN_KEY, []));
const q = ref("");
const busy = ref(false);
const loaded = ref(false);
const moving = ref<{ product: Schemas["ItemProductOut"]; from: Item } | null>(null);
const renaming = ref<string | null>(null);
const renameText = ref("");

async function load() {
  try {
    const [it, sg] = await Promise.all([ok(api.GET("/api/v1/items")), ok(api.GET("/api/v1/items/suggestions"))]);
    items.value = it;
    groups.value = sg.map((g) => ({ ...g, chosen: g.items.map((i) => i.key), title: g.name }));
  } catch (e) { toastError(e); }
  loaded.value = true;
}
onMounted(load);
const reloadAll = () => Promise.all([load(), loadProducts()]);
const visible = computed(() => groups.value.filter((g) => !hidden.value.includes(groupId(g))));
function hide(g: Group) { hidden.value = [...hidden.value, groupId(g)]; local.set(HIDDEN_KEY, hidden.value); }
function toggle(g: Group, key: string) { g.chosen = g.chosen.includes(key) ? g.chosen.filter((k) => k !== key) : [...g.chosen, key]; }

async function merge(g: Group) {
  if (g.chosen.length < 2) { toast("Отметьте хотя бы два товара", "error"); return; }
  busy.value = true;
  try {
    await ok(api.POST("/api/v1/items/merge", { body: { keys: g.chosen, name: g.title.trim() || g.name } }));
    toast(`Объединено в «${g.title}»`);
    await reloadAll();
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
function startRename(it: Item) { renaming.value = it.key; renameText.value = it.name; }
async function saveRename(it: Item) {
  if (!renameText.value.trim() || renameText.value.trim() === it.name) { renaming.value = null; return; }
  try {
    await ok(api.PATCH("/api/v1/items/{key}", { params: { path: { key: it.key } }, body: { name: renameText.value.trim() } }));
    renaming.value = null;
    toast("Товар переименован");
    await reloadAll();
  } catch (e) { toastError(e); }
}
async function onMoved() { moving.value = null; await reloadAll(); }

const list = computed(() => items.value.filter((i) =>
  !q.value || fuzzyScore(q.value, `${i.name} ${i.products.map((p) => `${p.name} ${p.brand || ""}`).join(" ")}`) >= 0.6));
const pkgs = (p: Schemas["ItemProductOut"]) => (p.packages ?? []).map((a) => fmtQty(a, p.base_unit)).join(" / ");
const brandsOf = (g: Schemas["ItemSuggestion"]["items"][number]) => g.products.map((p) => p.brand || "без бренда").join(", ");
</script>

<template>
  <div class="items">
    <p class="small muted">Товар — продукт без бренда: «Кефир 3,2%» любого производителя — одна строка в покупках и один остаток
      в запасах. Если в рецепте или плане важен именно этот бренд — отметьте 🎯.</p>

    <section v-if="visible.length" class="suggest">
      <h2>Похоже на один товар</h2>
      <div v-for="g in visible" :key="groupId(g)" class="group">
        <div class="inline">
          <input v-model="g.title" aria-label="Название объединённого товара">
          <button class="fill small" :disabled="busy || g.chosen.length < 2" @click="merge(g)">Объединить</button>
          <button class="text x" title="Не предлагать" aria-label="Не предлагать это объединение" @click="hide(g)">✕</button>
        </div>
        <label v-for="i in g.items" :key="i.key" class="check">
          <input type="checkbox" :checked="g.chosen.includes(i.key)" @change="toggle(g, i.key)">
          <span><b>{{ i.name }}</b> <span class="muted small">· {{ brandsOf(i) }}</span></span>
        </label>
      </div>
    </section>

    <span class="search">
      <input v-model="q" type="search" placeholder="Найти товар или бренд…" aria-label="Поиск товара">
      <button v-if="q" class="text clear" aria-label="Очистить" @click="q = ''">✕</button>
    </span>

    <div class="list">
      <div v-for="it in list" :key="it.key" class="item">
        <div class="inline">
          <template v-if="renaming === it.key">
            <input v-model="renameText" aria-label="Новое название товара" autofocus @keydown.enter="saveRename(it)" @keydown.esc="renaming = null">
            <button class="fill small" @click="saveRename(it)">OK</button>
            <button class="text x" aria-label="Отменить" @click="renaming = null">✕</button>
          </template>
          <template v-else>
            <b class="grow">{{ it.name }}</b>
            <span v-if="it.products.length > 1" class="badge">{{ it.products.length }} бренд.</span>
            <button class="text x" title="Переименовать товар" :aria-label="'Переименовать ' + it.name" @click="startRename(it)">✎</button>
          </template>
        </div>
        <div v-for="p in it.products" :key="p.id" class="prod small">
          <span class="grow ell">{{ p.brand || "без бренда" }} · {{ p.name }}<span v-if="pkgs(p)" class="muted"> · {{ pkgs(p) }}</span></span>
          <button class="text x" title="Перенести в другой товар" :aria-label="'Перенести ' + p.name" @click="moving = { product: p, from: it }">⇄</button>
        </div>
      </div>
      <p v-if="loaded && !list.length" class="muted pad">Ничего не найдено.</p>
    </div>
    <MoveModal v-if="moving" :product="moving.product" :from="moving.from" :items="items" @close="moving = null" @saved="onMoved" />
  </div>
</template>

<style scoped>
.items { display: flex; flex-direction: column; gap: 12px; }
p { margin: 0; }
h2 { font-size: 16px; }
.grow { flex: 1; min-width: 0; }
.inline { display: flex; align-items: center; gap: 8px; }
.inline input { flex: 1; min-width: 0; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
.x { min-width: 40px; min-height: 40px; padding: 0; color: var(--muted); }
/* предложение — «карандашом», как всё, что приложение предлагает само */
.suggest { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border-radius: var(--r-pot);
  border: 1.5px dashed var(--graphite); background: var(--graphite-soft); }
.group { display: flex; flex-direction: column; gap: 6px; padding-top: 10px; border-top: 1px dashed var(--line); }
.group:first-of-type { border-top: 0; padding-top: 0; }
.group input:not([type=checkbox]) { background: var(--enamel); }
.check { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }
.check input { width: 20px; height: 20px; min-height: 0; margin: 2px 0 0; accent-color: var(--rim); flex: none; }
.search { position: relative; max-width: 420px; }
.search input { padding-right: 44px; }
.search input::-webkit-search-cancel-button { display: none; }
.clear { position: absolute; right: 0; top: 0; min-width: 44px; padding: 0; color: var(--muted); }
.list { border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); }
.item { padding: 8px 8px 8px 16px; border-top: 1px solid var(--line); }
.item:first-child { border-top: 0; }
.prod { display: flex; align-items: center; gap: 6px; padding-left: 12px; color: var(--muted); }
.ell { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--enamel-2); color: var(--sky); white-space: nowrap; }
.pad { padding: 14px 16px; }
</style>
