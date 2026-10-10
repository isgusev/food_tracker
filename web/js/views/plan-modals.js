// План семьи: добавление блюда с порциями по людям и карточка блюда (кто что съел).
import { ref, computed, watch } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Picker, Macros } from "../components.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError, activeVariantOf } from "../product-finder.js";
import {
  state, toast, variantIndex, recipeById, recipeCategoryName, activeMembers, memberById,
} from "../store.js";
import { MEALS, MEAL_LABEL, bjuLine, fmt, fmtQty, grams, local, n, packageGrams, fmtWeekday, fmtDayMonth } from "../util.js";

// ---------- помощники для отображения блюда ----------
export const allEaten = (it) => it.portions.length > 0 && it.portions.every((p) => p.is_eaten);
export const portionOf = (it, memberId) => it.portions.find((p) => p.member_id === memberId) || null;

export function itemIcon(it) {
  if (allEaten(it)) return "✓";
  if (it.kind === "product") return "🛍";
  return it.state === "in_fridge" ? "◐" : "○";
}

export function itemBadge(it) {
  if (it.kind === "product") return { text: "Готовый продукт", cls: "info" };
  if (allEaten(it)) return { text: "Съедено", cls: "ok" };
  if (it.state === "in_fridge") {
    return it.fridge_enough === false
      ? { text: "В холодильнике не хватает", cls: "warn" }
      : { text: "Из холодильника", cls: "ok" };
  }
  if (it.fridge_pot_id && it.fridge_enough) {
    return { text: `Есть в холодильнике · свободно ${grams(n(it.fridge_available_g) - n(it.fridge_reserved_g))}`, cls: "info" };
  }
  if (it.fridge_pot_id) return { text: "Надо приготовить · в кастрюле не хватит", cls: "warn" };
  return { text: "Надо приготовить", cls: "warn" };
}

export function portionsSummary(it) {
  const named = it.portions.filter((p) => p.member_id != null).map((p) => `${p.member_name} ${fmt(p.weight_g)}`);
  const guests = it.portions.filter((p) => p.member_id == null);
  if (guests.length) named.push(guests.length === 1 ? `гость ${fmt(guests[0].weight_g)}` : `гости ×${guests.length}`);
  return named.join(" · ");
}

// Сумма КБЖУ порций одного члена семьи (onlyEaten — только съеденное)
export function memberMacros(items, memberId, onlyEaten = false) {
  const t = { calories: 0, proteins: 0, fats: 0, carbs: 0 };
  for (const it of items) {
    const p = portionOf(it, memberId);
    if (!p || (onlyEaten && !p.is_eaten)) continue;
    for (const k in t) t[k] += n(p[k]);
  }
  return t;
}

const portionMemoryKey = (kind, id) => `ft.portions.${kind}.${id}`;

// ---------- добавление блюда ----------
export const AddItemModal = {
  components: { Modal, Picker, Macros, ProductFinder, OffDraftCard },
  props: { date: String, meal: String, days: Array },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const kind = ref("recipe");
    const recipeId = ref(null);
    const variantId = ref(null);
    const draft = ref(null);          // продукт из Open Food Facts, ещё не в справочнике
    const meal = ref(props.meal || "lunch");
    const dates = ref([props.date]);
    const rows = ref(activeMembers.value.map((m) => ({ member_id: m.id, name: m.name, on: true, weight: 250 })));
    const guests = ref(0);
    const guestWeight = ref(250);
    const potStatus = ref(null);
    const busy = ref(false);
    const error = ref("");

    const recipeItems = computed(() =>
      [...state.recipes]
        .map((r) => ({
          id: r.id, label: r.name,
          group: recipeCategoryName.value[r.recipe_category_id] || "Без категории",
          right: `${fmt(r.calories_per_100g)} ккал/100 г`,
          right2: bjuLine({ proteins: r.proteins_per_100g, fats: r.fats_per_100g, carbs: r.carbs_per_100g }),
        }))
        .sort((a, b) => a.group.localeCompare(b.group, "ru") || a.label.localeCompare(b.label, "ru"))
    );
    const recipe = computed(() => recipeById.value[recipeId.value]);
    const portionHint = computed(() => {
      const r = recipe.value;
      return r ? n(r.estimated_cooked_weight) / Math.max(1, r.default_servings || 1) : null;
    });
    const per100 = computed(() => {
      if (kind.value === "recipe" && recipe.value) {
        const r = recipe.value;
        return { calories: n(r.calories_per_100g), proteins: n(r.proteins_per_100g), fats: n(r.fats_per_100g), carbs: n(r.carbs_per_100g) };
      }
      if (draft.value) {
        const k = draft.value.kbju;
        return k.calories === "" ? null : { calories: n(k.calories), proteins: n(k.proteins), fats: n(k.fats), carbs: n(k.carbs) };
      }
      const v = variantIndex.value[variantId.value];
      return v ? { calories: v.calories, proteins: v.proteins, fats: v.fats, carbs: v.carbs } : null;
    });

    // Упаковки готового продукта: можно сразу взять «по упаковке», а не вводить граммы
    const packages = computed(() => {
      if (kind.value !== "product") return [];
      if (draft.value) {
        const d = draft.value;
        return n(d.package_amount) > 0 && d.package_unit !== "pcs"
          ? [{ label: fmtQty(d.package_amount, d.package_unit), grams: n(d.package_amount) }] : [];
      }
      const p = variantIndex.value[variantId.value]?.product;
      if (!p) return [];
      return (p.packages || [])
        .map((pk) => ({ label: fmtQty(pk.amount, p.base_unit), grams: packageGrams(pk.amount, p.base_unit, p.piece_weight_g) }))
        .filter((pk) => pk.grams > 0);
    });
    const amountMode = ref("manual");   // "manual" | "package"
    const pkgIdx = ref(0);
    const pkgCount = ref(1);
    const pkgSplit = ref("each");       // "each" — каждому по упаковке, "shared" — одна на всех
    const pkg = computed(() => packages.value[pkgIdx.value] || packages.value[0] || null);
    function applyPackage() {
      if (amountMode.value !== "package" || !pkg.value) return;
      const g = pkg.value.grams * Math.max(1, n(pkgCount.value));
      const eaters = rows.value.filter((r) => r.on).length + n(guests.value);
      const each = pkgSplit.value === "each" ? g : g / Math.max(1, eaters);
      const w = Math.round(each * 10) / 10;
      for (const r of rows.value) r.weight = w;
      guestWeight.value = w;
    }
    watch([amountMode, pkgIdx, pkgCount, pkgSplit, guests, () => rows.value.map((r) => r.on).join()], applyPackage);
    const kcal = (w) => (per100.value ? (per100.value.calories * n(w)) / 100 : 0);
    const total = computed(() =>
      rows.value.filter((r) => r.on).reduce((s, r) => s + n(r.weight), 0) + n(guests.value) * n(guestWeight.value)
    );

    // Порции по умолчанию: как в прошлый раз для этого блюда, иначе стандартная порция
    function applyDefaults(memoryKey, fallback) {
      const saved = local.get(memoryKey, null);
      for (const r of rows.value) {
        const w = saved?.members?.[r.member_id];
        r.on = saved ? w != null : true;
        r.weight = Math.round(w ?? fallback);
      }
      guests.value = saved?.guests || 0;
      guestWeight.value = Math.round(saved?.guestWeight || fallback);
      return saved;
    }
    watch(recipeId, (id) => { if (id) applyDefaults(portionMemoryKey("r", id), portionHint.value || 250); });
    // готовый продукт: если есть упаковка — по умолчанию «по упаковке» (или как в прошлый раз)
    function productDefaults(memoryKey) {
      const saved = memoryKey ? applyDefaults(memoryKey, 100) : applyDefaults("ft.none", 100);
      pkgIdx.value = Math.min(saved?.pkgIdx || 0, Math.max(0, packages.value.length - 1));
      pkgCount.value = saved?.pkgCount || 1;
      pkgSplit.value = saved?.pkgSplit || "each";
      amountMode.value = packages.value.length && (!saved || saved.mode === "package") ? "package" : "manual";
      applyPackage();
    }
    watch(variantId, (id) => { if (id) productDefaults(portionMemoryKey("v", id)); });
    watch(draft, (d, old) => { if (d && !old) productDefaults(null); });

    watch([recipeId, total, kind], async () => {
      potStatus.value = null;
      if (kind.value !== "recipe" || !recipeId.value || !(total.value > 0)) return;
      try {
        potStatus.value = await api.get(`/plan/pot-status/${recipeId.value}`, { portion_g: total.value });
      } catch { /* подсказка необязательна */ }
    });
    const potFree = computed(() => (potStatus.value ? n(potStatus.value.available_g) - n(potStatus.value.planned_g) : 0));

    function toggleDate(d) {
      const i = dates.value.indexOf(d);
      if (i >= 0) { if (dates.value.length > 1) dates.value.splice(i, 1); }
      else dates.value.push(d);
    }

    async function save() {
      error.value = "";
      const portions = rows.value.filter((r) => r.on && n(r.weight) > 0).map((r) => ({ member_id: r.member_id, weight_g: n(r.weight) }));
      for (let i = 0; i < n(guests.value); i++) portions.push({ member_id: null, weight_g: n(guestWeight.value) });
      const body = { meal_type: meal.value, portions };
      if (kind.value === "recipe") {
        if (!recipeId.value) { error.value = "Выберите блюдо"; return; }
        body.recipe_id = recipeId.value;
      } else {
        if (!variantId.value && !draft.value) { error.value = "Выберите продукт"; return; }
        if (draft.value && (error.value = draftError(draft.value))) return;
        body.variant_id = variantId.value;
      }
      if (!portions.length) { error.value = "Отметьте, кто ест"; return; }
      busy.value = true;
      try {
        if (kind.value === "product" && draft.value) {
          // выбран продукт из Open Food Facts — сначала в справочник, потом в план
          const product = await saveDraft(draft.value);
          body.variant_id = activeVariantOf(product, draft.value.manufacturer || draft.value.brand);
          if (!body.variant_id) throw new Error("У сохранённого продукта нет активной версии КБЖУ");
        }
        for (const d of [...dates.value].sort()) await api.post("/plan", { ...body, date_day: d });
        local.set(portionMemoryKey(kind.value === "recipe" ? "r" : "v", body.recipe_id || body.variant_id), {
          members: Object.fromEntries(rows.value.filter((r) => r.on).map((r) => [r.member_id, n(r.weight)])),
          guests: n(guests.value), guestWeight: n(guestWeight.value),
          mode: amountMode.value, pkgIdx: pkgIdx.value, pkgCount: n(pkgCount.value), pkgSplit: pkgSplit.value,
        });
        toast(dates.value.length > 1 ? `Добавлено в ${dates.value.length} дн.` : "Добавлено в план");
        emit("saved");
      } catch (e) {
        error.value = e.message;
      } finally {
        busy.value = false;
      }
    }

    return {
      kind, recipeId, variantId, draft, packages, amountMode, pkgIdx, pkgCount, pkgSplit, meal, dates, rows, guests, guestWeight, potStatus, potFree, busy, error,
      recipeItems, portionHint, per100, kcal, total, MEALS, toggleDate, save, fmt, grams, fmtWeekday, fmtDayMonth, n,
    };
  },
  template: `
    <Modal title="Добавить в план" @close="$emit('close')">
      <div class="segmented">
        <button :class="{ on: kind === 'recipe' }" @click="kind = 'recipe'">🍲 Блюдо</button>
        <button :class="{ on: kind === 'product' }" @click="kind = 'product'">🛍️ Готовый продукт</button>
      </div>

      <label class="field" v-if="kind === 'recipe'"><span>Блюдо</span>
        <Picker :items="recipeItems" v-model="recipeId" placeholder="Поиск по рецептам…" autofocus />
        <span v-if="!recipeItems.length" class="tiny">Рецептов пока нет — создайте их в разделе «Рецепты».</span>
        <span v-else-if="portionHint" class="tiny">Стандартная порция ≈ {{ fmt(portionHint) }} г</span>
      </label>
      <div class="field" v-else><span>Продукт из магазина</span>
        <ProductFinder v-model="variantId" v-model:draft="draft" autofocus />
        <span v-if="!variantId && !draft" class="tiny muted">Сначала ищем в справочнике, не нашли — в Open Food Facts. 📷 — штрихкод камерой.</span>
      </div>
      <OffDraftCard v-if="kind === 'product' && draft" :draft="draft" />

      <div v-if="packages.length" class="stack tight">
        <div class="segmented">
          <button :class="{ on: amountMode === 'package' }" @click="amountMode = 'package'">По упаковке</button>
          <button :class="{ on: amountMode === 'manual' }" @click="amountMode = 'manual'">Вес вручную</button>
        </div>
        <div v-if="amountMode === 'package'" class="row small">
          <input type="number" min="1" step="1" v-model.number="pkgCount" style="width: 56px" aria-label="Сколько упаковок">
          <span class="muted">×</span>
          <select v-if="packages.length > 1" v-model.number="pkgIdx" style="width: auto">
            <option v-for="(p, i) in packages" :key="i" :value="i">{{ p.label }}</option>
          </select>
          <b v-else>{{ packages[0].label }}</b>
          <div class="segmented">
            <button :class="{ on: pkgSplit === 'each' }" @click="pkgSplit = 'each'">каждому</button>
            <button :class="{ on: pkgSplit === 'shared' }" @click="pkgSplit = 'shared'">на всех</button>
          </div>
        </div>
      </div>

      <div class="stack tight">
        <div class="row between"><b class="small">Кто ест и сколько, г</b><span class="small muted num">всего {{ grams(total) }}</span></div>
        <div v-for="r in rows" :key="r.member_id" class="row" style="flex-wrap: nowrap">
          <label class="row grow" style="gap: 8px; cursor: pointer"><input type="checkbox" v-model="r.on"><span class="ellipsis">{{ r.name }}</span></label>
          <input type="number" min="1" max="2000" step="any" v-model="r.weight" :disabled="!r.on || (packages.length && amountMode === 'package')" style="width: 90px">
          <span class="small muted num nowrap" style="width: 76px; text-align: right">{{ r.on && per100 ? fmt(kcal(r.weight)) + ' ккал' : '' }}</span>
        </div>
        <div class="row" style="flex-wrap: nowrap">
          <span class="grow small">Гости</span>
          <select v-model.number="guests" style="width: 70px"><option v-for="i in 11" :key="i" :value="i - 1">{{ i - 1 }}</option></select>
          <span class="small muted">по</span>
          <input type="number" min="1" max="2000" step="any" v-model="guestWeight" :disabled="!guests || (packages.length && amountMode === 'package')" style="width: 90px">
          <span style="width: 76px"></span>
        </div>
        <span class="tiny muted">Гости учитываются в кастрюле и покупках, но не в чьих-то КБЖУ.</span>
      </div>

      <div v-if="potStatus && potStatus.has_active_pot" class="alert" :class="potFree >= total ? 'info' : 'warn'">
        В холодильнике есть это блюдо: осталось {{ grams(potStatus.available_g) }}, из них запланировано {{ grams(potStatus.planned_g) }}.
        <template v-if="potFree >= total">Свободного хватает — возьмём из кастрюли.</template>
        <template v-else>Свободно только {{ grams(Math.max(0, potFree)) }} — блюдо попадёт в покупки как «надо приготовить».</template>
      </div>

      <label class="field"><span>Приём пищи</span>
        <div class="segmented" style="flex-wrap: wrap">
          <button v-for="m in MEALS" :key="m.key" :class="{ on: meal === m.key }" @click="meal = m.key">{{ m.label }}</button>
        </div>
      </label>

      <label class="field" v-if="days && days.length"><span>Дни (можно несколько)</span>
        <div class="row tight">
          <button v-for="d in days" :key="d" class="sm" :class="{ primary: dates.includes(d) }" @click="toggleDate(d)">
            {{ fmtWeekday(d) }} {{ fmtDayMonth(d) }}
          </button>
        </div>
      </label>

      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button @click="$emit('close')">Отмена</button>
        <button class="primary" :disabled="busy" @click="save">Добавить</button>
      </template>
    </Modal>`,
};

// ---------- карточка блюда ----------
export const ItemModal = {
  components: { Modal, Macros },
  props: { item: Object },
  emits: ["close", "changed"],
  setup(props, { emit }) {
    const it = ref(props.item);
    const weights = ref({});
    const resetWeights = () => { weights.value = Object.fromEntries(it.value.portions.map((p) => [p.id, n(p.weight_g)])); };
    resetWeights();
    const busy = ref(false);
    const error = ref("");
    const moveDate = ref(it.value.date_day);
    const moveMeal = ref(it.value.meal_type);
    const addWho = ref("");
    const addWeight = ref(n(it.value.portions[0]?.weight_g) || 200);

    async function run(fn, msg) {
      error.value = "";
      busy.value = true;
      try {
        const res = await fn();
        if (res) { it.value = res; resetWeights(); }
        if (msg) toast(msg);
        emit("changed", res || null);
        return res;
      } catch (e) {
        error.value = e.message;
      } finally {
        busy.value = false;
      }
    }
    const changed = (p) => n(weights.value[p.id]) !== n(p.weight_g);
    const eat = (p) => run(() => api.post(`/plan/portions/${p.id}/eat`, { weight_g: n(weights.value[p.id]) }), `${p.member_name || "Гость"}: съедено`);
    const uneat = (p) => run(() => api.post(`/plan/portions/${p.id}/uneat`), "Отметка снята");
    const detach = (p) => run(() => api.post(`/plan/portions/${p.id}/detach`), "Отвязано от холодильника");
    const saveWeight = (p) => run(() => api.patch(`/plan/portions/${p.id}`, { weight_g: n(weights.value[p.id]) }), "Порция обновлена");
    async function removePortion(p) {
      const last = it.value.portions.length === 1;
      if (last && !confirm("Это последняя порция — блюдо будет удалено из плана. Продолжить?")) return;
      const res = await run(() => api.del(`/plan/portions/${p.id}`), last ? "Блюдо удалено" : "Порция убрана");
      if (last && !error.value) emit("close");
      return res;
    }
    const eatAll = () => run(() => api.post(`/plan/${it.value.id}/eat`), "Отмечено: все поели");
    const move = () => run(() => api.patch(`/plan/${it.value.id}`, { date_day: moveDate.value, meal_type: moveMeal.value }), "Перенесено");
    async function removeItem() {
      const fromPot = it.value.portions.some((p) => p.is_eaten && p.eaten_from_pot_id);
      if (!confirm(`Удалить «${it.value.name}» из плана?${fromPot ? "\nСъеденное вернётся в кастрюлю." : ""}`)) return;
      await run(() => api.del(`/plan/${it.value.id}`), "Удалено");
      if (!error.value) emit("close");
    }
    const missing = computed(() => activeMembers.value.filter((m) => !it.value.portions.some((p) => p.member_id === m.id)));
    function addPortion() {
      const member_id = addWho.value === "guest" ? null : Number(addWho.value);
      return run(() => api.post(`/plan/${it.value.id}/portions`, { member_id, weight_g: n(addWeight.value) }), "Порция добавлена")
        .then(() => { addWho.value = ""; });
    }
    const badge = computed(() => itemBadge(it.value));
    const uneaten = computed(() => it.value.portions.filter((p) => !p.is_eaten).length);
    return {
      it, weights, busy, error, moveDate, moveMeal, addWho, addWeight, missing, badge, uneaten, MEALS, MEAL_LABEL,
      changed, eat, uneat, detach, saveWeight, removePortion, eatAll, move, removeItem, addPortion,
      grams, fmt, fmtWeekday, fmtDayMonth, memberById,
    };
  },
  template: `
    <Modal :title="it.name" wide @close="$emit('close')">
      <div class="row">
        <span class="badge" :class="badge.cls">{{ badge.text }}</span>
        <span class="muted small">{{ MEAL_LABEL[it.meal_type] }} · {{ fmtWeekday(it.date_day) }} {{ fmtDayMonth(it.date_day) }}</span>
        <span class="muted small" v-if="it.fridge_pot_id">· в кастрюле {{ grams(it.fridge_available_g) }}</span>
      </div>

      <div class="card flush table-wrap">
        <table class="tbl">
          <thead><tr><th>Кто</th><th class="r">Порция, г</th><th class="r">ккал</th><th>Статус</th><th></th></tr></thead>
          <tbody>
            <tr v-for="p in it.portions" :key="p.id">
              <td><b v-if="p.member_id">{{ p.member_name }}</b><span v-else class="muted">Гость</span></td>
              <td class="r"><input type="number" min="1" max="2000" step="any" v-model="weights[p.id]" style="width: 84px"
                     @keydown.enter="p.is_eaten ? saveWeight(p) : eat(p)"></td>
              <td class="r num">{{ fmt(p.calories) }}</td>
              <td>
                <span v-if="p.is_eaten" class="badge ok">✓ съел{{ p.eaten_from_pot_id ? ' · из холодильника' : '' }}</span>
                <span v-else class="badge">в плане</span>
              </td>
              <td class="r nowrap">
                <button v-if="changed(p)" class="sm" :disabled="busy" @click="saveWeight(p)">Сохранить</button>
                <button v-if="!p.is_eaten" class="sm primary" :disabled="busy" @click="eat(p)" title="Съедено (вес — из поля)">✓ Съел</button>
                <button v-else class="sm ghost" :disabled="busy" @click="uneat(p)" title="Отменить «съедено»">↺</button>
                <button v-if="p.is_eaten && p.eaten_from_pot_id" class="sm ghost" :disabled="busy" @click="detach(p)"
                        title="Ели не из этой кастрюли — вес в неё не вернётся">без холодильника</button>
                <button class="sm ghost" :disabled="busy" @click="removePortion(p)" title="Убрать порцию">✕</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="row">
        <select v-model="addWho" style="max-width: 200px">
          <option value="">+ Добавить едока…</option>
          <option v-for="m in missing" :key="m.id" :value="m.id">{{ m.name }}</option>
          <option value="guest">Гость</option>
        </select>
        <template v-if="addWho">
          <input type="number" min="1" max="2000" step="any" v-model="addWeight" style="width: 90px"><span class="small muted">г</span>
          <button class="sm" :disabled="busy" @click="addPortion">Добавить</button>
        </template>
      </div>

      <details>
        <summary class="small muted" style="cursor: pointer">Перенести на другой день / приём пищи</summary>
        <div class="row" style="margin-top: 8px">
          <input type="date" v-model="moveDate" style="width: 170px">
          <select v-model="moveMeal" style="width: 140px"><option v-for="m in MEALS" :key="m.key" :value="m.key">{{ m.label }}</option></select>
          <button class="sm" :disabled="busy" @click="move">Перенести</button>
        </div>
      </details>

      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button class="danger" :disabled="busy" @click="removeItem">Удалить блюдо</button>
        <span class="grow"></span>
        <button v-if="uneaten" class="primary" :disabled="busy" @click="eatAll">✓ Все поели</button>
      </template>
    </Modal>`,
};
