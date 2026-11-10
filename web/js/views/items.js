// Товары — базовые наименования без бренда («Кефир 3,2%»): по ним идут запасы и покупки.
// Приложение предлагает объединить похожие («Кефир 3.2% Домик в деревне» + «Кефир 3,2%»),
// вы подтверждаете или правите название; продукт можно перенести в другой товар.
import { ref, computed, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal } from "../components.js";
import { loadProducts, toast, toastError } from "../store.js";
import { fmtQty, fuzzyScore, local } from "../util.js";

const HIDDEN_KEY = "ft.itemSuggestionsHidden";
const groupId = (g) => g.items.map((i) => i.key).sort().join("|");

// Перенести продукт в другой товар или выделить в новый
const MoveModal = {
  components: { Modal },
  props: { product: Object, from: Object, items: Array },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const target = ref("");
    const newName = ref("");
    const busy = ref(false);
    const options = computed(() => props.items.filter((i) => i.key !== props.from.key));
    async function save() {
      busy.value = true;
      try {
        await api.put(`/items/products/${props.product.id}`, target.value === "__new" ? { new_name: newName.value } : { item_key: target.value });
        toast("Продукт перенесён");
        emit("saved");
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { target, newName, busy, options, save };
  },
  template: `
    <Modal :title="'Перенести: ' + product.name" @close="$emit('close')">
      <div class="small muted">Сейчас в товаре «{{ from.name }}». В покупках и запасах продукт будет считаться вместе с товаром, куда перенесёте.</div>
      <label class="field"><span>В товар</span>
        <select v-model="target">
          <option value="" disabled>— выберите —</option>
          <option value="__new">+ Новый товар…</option>
          <option v-for="i in options" :key="i.key" :value="i.key">{{ i.name }}</option>
        </select></label>
      <label v-if="target === '__new'" class="field"><span>Название нового товара</span><input v-model="newName" placeholder="Кефир 1%"></label>
      <template #foot><button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy || !target || (target === '__new' && !newName.trim())" @click="save">Перенести</button></template>
    </Modal>`,
};

export const ItemsPanel = {
  components: { MoveModal },
  setup() {
    const items = ref([]);
    const suggestions = ref([]);
    const hidden = ref(local.get(HIDDEN_KEY, []));
    const q = ref("");
    const busy = ref(false);
    const moving = ref(null);       // { product, from }
    const renaming = ref(null);     // key
    const renameText = ref("");

    async function load() {
      try {
        [items.value, suggestions.value] = await Promise.all([api.get("/items"), api.get("/items/suggestions")]);
        for (const g of suggestions.value) { g.chosen = g.items.map((i) => i.key); g.title = g.name; }
      } catch (e) { toastError(e); }
    }
    onMounted(load);
    const visibleSuggestions = computed(() => suggestions.value.filter((g) => !hidden.value.includes(groupId(g))));
    function hide(g) { hidden.value = [...hidden.value, groupId(g)]; local.set(HIDDEN_KEY, hidden.value); }

    async function merge(g) {
      if (g.chosen.length < 2) { toast("Отметьте хотя бы два товара", "error"); return; }
      busy.value = true;
      try {
        await api.post("/items/merge", { keys: g.chosen, name: g.title });
        toast(`Объединено в «${g.title}»`);
        await Promise.all([load(), loadProducts()]);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    function startRename(it) { renaming.value = it.key; renameText.value = it.name; }
    async function saveRename(it) {
      try { await api.patch(`/items/${it.key}`, { name: renameText.value }); renaming.value = null; await Promise.all([load(), loadProducts()]); }
      catch (e) { toastError(e); }
    }
    async function onMoved() { moving.value = null; await Promise.all([load(), loadProducts()]); }

    const list = computed(() => items.value
      .filter((i) => !q.value || fuzzyScore(q.value, `${i.name} ${i.products.map((p) => `${p.name} ${p.brand || ""}`).join(" ")}`) >= 0.6)
      .map((i) => ({ ...i, multi: i.products.length > 1 })));
    const pkgs = (p) => (p.packages.length ? p.packages.map((a) => fmtQty(a, p.base_unit)).join(" / ") : "");
    return { items, list, q, busy, visibleSuggestions, hide, merge, moving, renaming, renameText, startRename, saveRename, onMoved, pkgs };
  },
  template: `
    <div class="stack">
      <div class="tiny muted">Товар — продукт без бренда: «Кефир 3,2%» любого производителя — одна строка в покупках
        и один остаток в запасах. Если в рецепте или плане важен именно этот бренд — отметьте «🎯 именно этот».</div>

      <div v-if="visibleSuggestions.length" class="card stack">
        <h3>Похоже на один товар</h3>
        <div v-for="g in visibleSuggestions" :key="g.items.map(i => i.key).join()" class="stack tight suggest-group">
          <div class="row" style="flex-wrap: nowrap">
            <input v-model="g.title" class="grow" aria-label="Название объединённого товара">
            <button class="sm primary" :disabled="busy" @click="merge(g)">Объединить</button>
            <button class="sm ghost" @click="hide(g)" title="Не предлагать">✕</button>
          </div>
          <label v-for="i in g.items" :key="i.key" class="row small" style="gap: 8px; cursor: pointer; flex-wrap: nowrap; align-items: flex-start">
            <input type="checkbox" :value="i.key" v-model="g.chosen">
            <span style="min-width: 0"><b>{{ i.name }}</b> <span class="muted">· {{ i.products.map(p => p.brand || 'без бренда').join(', ') }}</span></span>
          </label>
        </div>
      </div>

      <div class="clearable" style="max-width: 320px">
        <input v-model="q" placeholder="Поиск товара или бренда…">
        <button v-if="q" type="button" class="clear-btn" aria-label="Очистить" @click="q = ''">✕</button>
      </div>
      <div class="card flush">
        <div v-for="it in list" :key="it.key" class="item-row">
          <div class="row" style="flex-wrap: nowrap">
            <template v-if="renaming === it.key">
              <input v-model="renameText" class="grow" @keydown.enter="saveRename(it)">
              <button class="sm primary" @click="saveRename(it)">OK</button>
              <button class="sm ghost" @click="renaming = null">✕</button>
            </template>
            <template v-else>
              <b class="grow">{{ it.name }}</b>
              <span v-if="it.multi" class="badge info">{{ it.products.length }} бренд.</span>
              <button class="sm ghost" @click="startRename(it)" title="Переименовать товар">✎</button>
            </template>
          </div>
          <div v-for="p in it.products" :key="p.id" class="row tiny muted" style="flex-wrap: nowrap; padding-left: 10px">
            <span class="grow ellipsis">{{ p.brand || 'без бренда' }} · {{ p.name }}<template v-if="pkgs(p)"> · {{ pkgs(p) }}</template></span>
            <button class="sm ghost" style="padding: 0 6px" @click="moving = { product: p, from: it }" title="Перенести в другой товар">⇄</button>
          </div>
        </div>
        <div v-if="!list.length" class="empty">Ничего не найдено</div>
      </div>
      <MoveModal v-if="moving" :product="moving.product" :from="moving.from" :items="items" @close="moving = null" @saved="onMoved" />
    </div>`,
};
