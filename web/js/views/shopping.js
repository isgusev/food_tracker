// Общий список покупок семьи: формируется из плана за вычетом запасов,
// «куплено» сразу кладёт товар в запасы; второй телефон видит отметки.
import { ref, computed, onMounted, onBeforeUnmount } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Picker } from "../components.js";
import { state, ensureCatalog, toast, toastError } from "../store.js";
import { addDays, fmt, fmtDayMonth, fmtQty, n, startOfWeek, today, UNIT_LABEL } from "../util.js";

const POLL_MS = 15000;

function pkgText(l) {
  if (l.package_amount && l.package_count) {
    const one = fmtQty(l.package_amount, l.unit);
    return l.package_count === 1 && l.unit === "pcs" && n(l.package_amount) === 1 ? fmtQty(l.package_count, "pcs") : `${l.package_count} × ${one}`;
  }
  return l.needed ? fmtQty(l.needed, l.unit) : "";
}

// Позиция после «куплено»: количество, цена, срок
const BoughtModal = {
  components: { Modal },
  props: { line: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const qty = ref(n(props.line.bought_quantity));
    const price = ref(props.line.price != null ? n(props.line.price) : "");
    const expires = ref(props.line.expires_on || "");
    const busy = ref(false);
    async function save() {
      busy.value = true;
      try {
        const res = await api.patch(`/shopping-lists/lines/${props.line.id}`, {
          quantity: n(qty.value), price: price.value === "" ? null : n(price.value), expires_on: expires.value || null,
        });
        emit("saved", res);
      } catch (e) { toastError(e); } finally { busy.value = false; }
    }
    return { qty, price, expires, busy, save, UNIT_LABEL };
  },
  template: `
    <Modal :title="line.product_name" @close="$emit('close')">
      <div class="grid-2">
        <label class="field"><span>Купили, {{ UNIT_LABEL[line.unit] }}</span><input type="number" min="0.1" step="any" v-model="qty"></label>
        <label class="field"><span>Цена за всё, ₽</span><input type="number" min="0" step="0.01" v-model="price" placeholder="необязательно"></label>
      </div>
      <label class="field"><span>Годен до</span><input type="date" v-model="expires"><span class="tiny">Необязательно — пригодится для напоминаний</span></label>
      <template #foot>
        <button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy" @click="save">Сохранить</button>
      </template>
    </Modal>`,
};

export const ShoppingView = {
  components: { BoughtModal, Picker },
  props: { query: Object },
  setup(props) {
    const lst = ref(null);
    const loading = ref(false);
    // Оценка суммы — по последней цене товара из прошлых покупок
    const prices = ref({});
    api.get("/finance/prices").then((r) => { prices.value = Object.fromEntries(r.map((p) => [p.item_key, n(p.unit_price)])); }).catch(() => {});
    const lineQty = (l) => (l.package_amount && l.package_count ? n(l.package_amount) * l.package_count : n(l.needed));
    const estimate = (l) => (prices.value[l.item_key] != null && lineQty(l) > 0 ? prices.value[l.item_key] * lineQty(l) : null);
    const estTotal = computed(() => {
      let sum = 0, unknown = 0;
      for (const l of lst.value?.lines || []) {
        if (l.is_checked) continue;
        const e = estimate(l);
        if (e == null) unknown++; else sum += e;
      }
      return { sum, unknown };
    });
    const start = ref(props.query?.start || today());
    const end = ref(props.query?.end || addDays(startOfWeek(today()), 6));
    const editing = ref(null);
    const extraOpen = ref(false);
    const extraProduct = ref(null);
    const extraQty = ref("");
    let timer = null;

    async function refresh(silent = true) {
      try {
        const res = await api.get("/shopping-lists/active");
        lst.value = res;
        if (res && !props.query?.start) { start.value = res.start_date; end.value = res.end_date; }
      } catch (e) { if (!silent) toastError(e); }
    }
    async function generate() {
      if (end.value < start.value) { toast("Дата окончания раньше даты начала", "error"); return; }
      loading.value = true;
      try {
        lst.value = await api.post("/shopping-lists", { start_date: start.value, end_date: end.value });
        toast("Список обновлён по плану и запасам");
      } catch (e) { toastError(e); } finally { loading.value = false; }
    }
    const onVisible = () => { if (!document.hidden) refresh(); };
    onMounted(async () => {
      await refresh(false);
      // Пришли из плана с конкретным периодом — сразу формируем
      if (props.query?.start && (!lst.value || lst.value.start_date !== start.value || lst.value.end_date !== end.value)) await generate();
      timer = setInterval(() => { if (!document.hidden && !editing.value) refresh(); }, POLL_MS);
      document.addEventListener("visibilitychange", onVisible);
      ensureCatalog().catch(() => {});
    });
    onBeforeUnmount(() => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); });

    const groups = computed(() => {
      const map = new Map();
      for (const l of lst.value?.lines || []) {
        if (l.is_checked) continue;
        const g = l.category_name || "Без категории";
        if (!map.has(g)) map.set(g, []);
        map.get(g).push(l);
      }
      return [...map.entries()].map(([name, list]) => ({ name, list }));
    });
    const bought = computed(() => (lst.value?.lines || []).filter((l) => l.is_checked));
    const spent = computed(() => bought.value.reduce((s, l) => s + n(l.price), 0));

    async function act(fn) {
      try { lst.value = await fn(); } catch (e) { toastError(e); }
    }
    const check = (l) => act(() => api.post(`/shopping-lists/lines/${l.id}/check`, {}));
    const uncheck = (l) => act(() => api.post(`/shopping-lists/lines/${l.id}/uncheck`));
    const remove = (l) => act(() => api.del(`/shopping-lists/lines/${l.id}`));
    async function addExtra() {
      if (!extraProduct.value) return;
      await act(() => api.post(`/shopping-lists/${lst.value.id}/lines`, { product_id: extraProduct.value, quantity: extraQty.value ? n(extraQty.value) : null }));
      extraProduct.value = null; extraQty.value = ""; extraOpen.value = false;
    }
    async function close() {
      const unpriced = bought.value.filter((l) => l.price == null).length;
      if (!confirm(`Закрыть список?${unpriced ? `\nУ ${unpriced} покупок не указана цена — её можно будет дописать в запасах.` : ""}`)) return;
      try { await api.post(`/shopping-lists/${lst.value.id}/close`); lst.value = null; toast("Список закрыт"); }
      catch (e) { toastError(e); }
    }
    function preset(kind) {
      const t = today(), w = startOfWeek(t);
      if (kind === "rest") { start.value = t; end.value = addDays(w, 6); }
      if (kind === "next") { start.value = addDays(w, 7); end.value = addDays(w, 13); }
      if (kind === "3d") { start.value = t; end.value = addDays(t, 2); }
    }
    const productItems = computed(() => state.products.map((p) => ({ id: p.id, label: p.name, sub: p.brand?.name })));
    const asText = () => groups.value.map((g) => `${g.name}:\n` + g.list.map((l) => `☐ ${l.product_name} — ${pkgText(l)}`).join("\n")).join("\n\n");
    async function copy() {
      try { await navigator.clipboard.writeText(asText()); toast("Список скопирован"); }
      catch { toast("Не удалось скопировать", "error"); }
    }

    return {
      lst, loading, start, end, editing, estimate, estTotal, extraOpen, extraProduct, extraQty, groups, bought, spent, productItems,
      generate, check, uncheck, remove, addExtra, close, preset, copy, pkgText, fmt, fmtQty, fmtDayMonth, n,
      onSaved: (res) => { lst.value = res; editing.value = null; },
    };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Покупки</h1>
        <div class="row" v-if="lst">
          <button @click="copy">📋 Копировать</button>
          <button @click="close">Закрыть список</button>
        </div>
      </div>

      <div class="card stack" style="margin-bottom: 14px">
        <div class="row">
          <label class="field" style="width: 170px"><span>С</span><input type="date" v-model="start"></label>
          <label class="field" style="width: 170px"><span>По</span><input type="date" v-model="end"></label>
          <button class="primary" style="align-self: flex-end" :disabled="loading" @click="generate">{{ lst ? 'Пересчитать' : 'Сформировать список' }}</button>
        </div>
        <div class="row tight">
          <button class="sm" @click="preset('rest')">До конца недели</button>
          <button class="sm" @click="preset('next')">Следующая неделя</button>
          <button class="sm" @click="preset('3d')">3 дня</button>
        </div>
        <div class="tiny muted">
          Считается из плана: несъеденные порции блюд, которых нет в холодильнике, минус то, что уже есть в запасах.
          Список общий для семьи — отметки «куплено» видны на всех телефонах, а товар сразу попадает в «Холодильник → Продукты».
        </div>
      </div>

      <div v-if="!lst" class="card empty">Активного списка нет. Выберите период и нажмите «Сформировать список».</div>
      <template v-else>
        <div class="row between small muted" style="margin-bottom: 8px">
          <span>{{ fmtDayMonth(lst.start_date) }} — {{ fmtDayMonth(lst.end_date) }} · осталось {{ lst.lines.length - bought.length }}, куплено {{ bought.length }}
            <template v-if="estTotal.sum"> · ≈ {{ fmt(estTotal.sum) }} ₽<template v-if="estTotal.unknown"> + {{ estTotal.unknown }} без цены</template></template></span>
          <button class="sm ghost" @click="extraOpen = !extraOpen">+ Внеплановая покупка</button>
        </div>
        <div v-if="extraOpen" class="card row" style="margin-bottom: 10px">
          <div class="grow" style="min-width: 200px"><Picker :items="productItems" v-model="extraProduct" placeholder="Что купить…" /></div>
          <input type="number" min="0.1" step="any" v-model="extraQty" placeholder="Сколько" style="width: 110px">
          <button class="sm primary" :disabled="!extraProduct" @click="addExtra">Добавить</button>
        </div>

        <div v-if="!groups.length && !bought.length" class="card empty">Покупать нечего — всё есть дома или план пуст.</div>
        <div v-if="groups.length" class="card flush" style="overflow: hidden">
          <template v-for="g in groups" :key="g.name">
            <div class="shop-cat">{{ g.name }}</div>
            <div v-for="l in g.list" :key="l.id" class="shop-item">
              <input type="checkbox" @change="check(l)" :aria-label="'Купил: ' + l.product_name">
              <span class="grow shop-name">{{ l.product_name }}
                <span v-if="l.is_staple" class="badge warn">заканчивается</span>
                <span v-if="l.is_extra" class="badge">вне плана</span>
                <span v-if="l.brand" class="tiny muted"> · {{ l.brand }}</span></span>
              <span class="nowrap" style="text-align: right"><b class="num">{{ pkgText(l) }}</b>
                <div v-if="estimate(l) != null" class="tiny muted num">≈ {{ fmt(estimate(l)) }} ₽</div></span>
              <button class="ghost icon sm" @click="remove(l)" title="Убрать из списка">✕</button>
            </div>
          </template>
        </div>

        <template v-if="bought.length">
          <div class="row between small muted" style="margin: 16px 0 8px">
            <span>Куплено — уже в запасах</span>
            <span v-if="spent">потрачено {{ fmt(spent, 2) }} ₽</span>
          </div>
          <div class="card flush" style="overflow: hidden">
            <div v-for="l in bought" :key="l.id" class="shop-item done">
              <input type="checkbox" checked @change="uncheck(l)" :aria-label="'Не купил: ' + l.product_name">
              <span class="grow shop-name">{{ l.product_name }}</span>
              <span class="small muted num nowrap">{{ fmtQty(l.bought_quantity, l.unit) }}<template v-if="l.price != null"> · {{ fmt(l.price, 2) }} ₽</template><template v-if="l.expires_on"> · до {{ fmtDayMonth(l.expires_on) }}</template></span>
              <button class="sm" @click="editing = l">{{ l.price == null ? 'Цена…' : 'Изменить' }}</button>
            </div>
          </div>
        </template>
      </template>

      <BoughtModal v-if="editing" :line="editing" @close="editing = null" @saved="onSaved" />
    </div>`,
};
