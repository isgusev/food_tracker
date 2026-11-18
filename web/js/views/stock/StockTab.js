import { ref, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, BarcodeScanner } from "../../components.js";
import { state, ensureCatalog, toast, toastError } from "../../store.js";
import { fmt, fmtDateTime, fmtDayMonth, fmtQty, matches, n, today, UNIT_LABEL } from "../../util.js";
import { PacksEditor, packsBody, defaultPackAmount, productById } from "../../marking.js";
import { AddLotModal } from "./AddLotModal.js";
import { ItemModal } from "./ItemModal.js";
import { QuickInventory } from "./QuickInventory.js";

export const StockTab = {
  components: { AddLotModal, ItemModal, QuickInventory },
  setup() {
    const items = ref([]);
    const q = ref("");
    const adding = ref(false);
    const opened = ref(null);
    const quick = ref(false);
    async function load() {
      try { await ensureCatalog(); items.value = await api.get("/stock"); } catch (e) { toastError(e); }
    }
    onMounted(load);
    const list = computed(() => items.value.filter((i) => matches(i.name, q.value)));
    const groups = computed(() => {
      const map = new Map();
      for (const i of list.value) {
        const g = i.category_name || "Без категории";
        if (!map.has(g)) map.set(g, []);
        map.get(g).push(i);
      }
      return [...map.entries()].map(([name, list]) => ({ name, list }));
    });
    const checks = computed(() => items.value.filter((i) => i.needs_check).length);
    return {
      items, q, adding, opened, quick, groups, checks, load, fmtQty, fmtDayMonth, n, today: today(),
      onSaved: (list) => { if (Array.isArray(list)) items.value = list; else load(); adding.value = false; quick.value = false; },
    };
  },
  template: `
    <div class="stack">
      <div class="row">
        <input v-model="q" placeholder="Поиск…" style="max-width: 240px">
        <button class="primary sm" @click="adding = true">+ Добавить</button>
        <button class="sm" @click="quick = true" :disabled="!items.length">Инвентаризация</button>
        <span v-if="checks" class="badge warn">учёт сбился: {{ checks }}</span>
      </div>
      <div v-if="!items.length" class="card empty">Запасов пока нет. Они появятся, когда отметите покупки в списке, или добавьте вручную.</div>
      <div v-else class="card flush" style="overflow: hidden">
        <template v-for="g in groups" :key="g.name">
          <div class="shop-cat">{{ g.name }}</div>
          <div v-for="i in g.list" :key="i.item_key" class="list-item clickable" @click="opened = i">
            <div class="grow">
              <b>{{ i.name }}</b>
              <span v-if="i.is_staple" class="badge" style="margin-left: 6px">базовый</span>
              <span v-if="i.is_low" class="badge warn" style="margin-left: 4px">заканчивается</span>
              <span v-if="i.needs_check" class="badge warn" style="margin-left: 4px">учёт сбился</span>
              <div class="tiny muted" v-if="i.nearest_expiry">годен до {{ fmtDayMonth(i.nearest_expiry) }}<span v-if="n(i.expired) > 0" style="color: var(--danger)"> · просрочено {{ fmtQty(i.expired, i.unit) }}</span></div>
            </div>
            <b class="num nowrap" v-if="!i.is_staple">{{ fmtQty(i.remaining, i.unit) }}</b>
          </div>
        </template>
      </div>
      <AddLotModal v-if="adding" @close="adding = false" @saved="onSaved" />
      <ItemModal v-if="opened" :item="opened" @close="opened = null" @saved="onSaved" />
      <QuickInventory v-if="quick" :items="items" @close="quick = false" @saved="onSaved" />
    </div>`,
};
