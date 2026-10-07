// Список покупок на период: группировка по категориям, отметки «куплено», экспорт.
import { ref, computed, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { toast, toastError } from "../store.js";
import { addDays, daysBetween, fmtDayMonth, grams, local, startOfWeek, today } from "../util.js";

export const ShoppingView = {
  props: { query: Object },
  setup(props) {
    const start = ref(props.query?.start || today());
    const end = ref(props.query?.end || addDays(startOfWeek(today()), 6));
    const items = ref([]);
    const loading = ref(false);
    const error = ref("");
    const checkedKey = computed(() => `ft.shop.${start.value}.${end.value}`);
    const checked = ref({});

    async function load() {
      error.value = "";
      if (end.value < start.value) { error.value = "Дата окончания раньше даты начала"; items.value = []; return; }
      if (daysBetween(start.value, end.value) > 90) { error.value = "Период не должен превышать 90 дней"; return; }
      loading.value = true;
      try {
        const r = await api.get("/shopping-list", { start_date: start.value, end_date: end.value });
        items.value = r.items;
        checked.value = local.get(checkedKey.value, {});
        history.replaceState(null, "", `#/shopping?start=${start.value}&end=${end.value}`);
      } catch (e) { toastError(e); } finally { loading.value = false; }
    }
    watch([start, end], load);
    onMounted(load);

    const groups = computed(() => {
      const map = new Map();
      for (const it of items.value) {
        const g = it.category_name || "Без категории";
        if (!map.has(g)) map.set(g, []);
        map.get(g).push(it);
      }
      return [...map.entries()].map(([name, list]) => ({ name, list }));
    });
    const doneCount = computed(() => items.value.filter((i) => checked.value[i.variant_id]).length);

    function toggle(id) {
      checked.value = { ...checked.value, [id]: !checked.value[id] };
      local.set(checkedKey.value, checked.value);
    }
    function resetChecks() { checked.value = {}; local.set(checkedKey.value, {}); }

    function preset(kind) {
      const t = today();
      const w = startOfWeek(t);
      if (kind === "rest") { start.value = t; end.value = addDays(w, 6); }
      if (kind === "next") { start.value = addDays(w, 7); end.value = addDays(w, 13); }
      if (kind === "3d") { start.value = t; end.value = addDays(t, 2); }
    }

    const asText = () => groups.value
      .map((g) => `${g.name}:\n` + g.list.map((i) => `${checked.value[i.variant_id] ? "✓" : "☐"} ${i.product_name} — ${grams(i.weight_g)}`).join("\n"))
      .join("\n\n");
    async function copy() {
      try { await navigator.clipboard.writeText(asText()); toast("Список скопирован"); }
      catch { toast("Не удалось скопировать", "error"); }
    }
    function csv() {
      const rows = [["category", "product", "weight_g", "bought"]].concat(
        items.value.map((i) => [i.category_name || "", i.product_name, i.weight_g, checked.value[i.variant_id] ? 1 : 0])
      );
      const text = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\n");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob(["﻿" + text], { type: "text/csv;charset=utf-8" }));
      a.download = `shopping_${start.value}_${end.value}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    }

    return { start, end, items, groups, checked, doneCount, loading, error, toggle, resetChecks, preset, copy, csv, grams, fmtDayMonth };
  },
  template: `
    <div>
      <div class="page-head">
        <h1>Список покупок</h1>
        <div class="row" v-if="items.length">
          <button @click="copy">📋 Копировать</button>
          <button @click="csv">⬇ CSV</button>
        </div>
      </div>

      <div class="card stack" style="margin-bottom: 14px">
        <div class="row">
          <label class="field" style="width: 170px"><span>С</span><input type="date" v-model="start"></label>
          <label class="field" style="width: 170px"><span>По</span><input type="date" v-model="end"></label>
          <div class="row tight" style="align-self: flex-end">
            <button class="sm" @click="preset('rest')">До конца недели</button>
            <button class="sm" @click="preset('next')">Следующая неделя</button>
            <button class="sm" @click="preset('3d')">3 дня</button>
          </div>
        </div>
        <div class="tiny muted">
          В список попадают ещё не приготовленные блюда (○) — разложенные на ингредиенты с учётом числа едоков — и готовые продукты (🛍).
          Блюда, которые уже есть в холодильнике, и съеденное не учитываются.
        </div>
      </div>

      <div v-if="error" class="alert error">{{ error }}</div>
      <div v-else-if="loading && !items.length" class="empty">Загрузка…</div>
      <div v-else-if="!items.length" class="card empty">На {{ fmtDayMonth(start) }} — {{ fmtDayMonth(end) }} покупать нечего. Добавьте блюда в <a href="#/plan">план</a>.</div>
      <template v-else>
        <div class="row between small muted" style="margin-bottom: 8px">
          <span>Куплено {{ doneCount }} из {{ items.length }}</span>
          <button class="sm ghost" v-if="doneCount" @click="resetChecks">Сбросить отметки</button>
        </div>
        <div class="card flush" style="overflow: hidden">
          <template v-for="g in groups" :key="g.name">
            <div class="shop-cat">{{ g.name }}</div>
            <label v-for="i in g.list" :key="i.variant_id" class="shop-item" :class="{ done: checked[i.variant_id] }">
              <input type="checkbox" :checked="!!checked[i.variant_id]" @change="toggle(i.variant_id)">
              <span class="grow shop-name">{{ i.product_name }}</span>
              <b class="num nowrap">{{ grams(i.weight_g) }}</b>
            </label>
          </template>
        </div>
      </template>
    </div>`,
};
