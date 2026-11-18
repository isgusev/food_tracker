import { ref, computed, watch } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { Modal, Picker, Macros } from "../../components.js";
import { ProductFinder, OffDraftCard, saveDraft, draftError, activeVariantOf } from "../../product-finder.js";
import {
  state, toast, variantIndex, recipeById, recipeCategoryName, activeMembers, memberById,
} from "../../store.js";
import { MEALS, MEAL_LABEL, bjuLine, fmt, fmtQty, grams, local, n, packageGrams, fmtWeekday, fmtDayMonth } from "../../util.js";

// ---------- помощники для отображения блюда ----------
import { portionMemoryKey } from "./shared.js";

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
    const exact = ref(false);         // «именно этот вариант» — в покупки этот бренд
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
    // нет «как в прошлый раз» на этом устройстве — типичные порции с сервера (по съеденному
    // за 90 дней, иначе по другим членам семьи или по цели ккал на приём пищи)
    async function typicalDefaults(id) {
      try {
        const t = await api.get("/plan/typical-portions", { meal_type: meal.value, recipe_id: id });
        if (recipeId.value !== id) return;
        const by = Object.fromEntries(t.map((x) => [x.member_id, n(x.weight_g)]));
        for (const r of rows.value) if (by[r.member_id] != null) r.weight = by[r.member_id];
      } catch { /* подсказка необязательна */ }
    }
    watch(recipeId, (id) => {
      if (!id) return;
      if (!applyDefaults(portionMemoryKey("r", id), portionHint.value || 250)) typicalDefaults(id);
    });
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
        if (variantIndex.value[variantId.value]?.kbjuMissing) { error.value = "Сначала внесите КБЖУ продукта — поля выше"; return; }
        if (draft.value && (error.value = draftError(draft.value))) return;
        body.variant_id = variantId.value;
        body.exact = exact.value;
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
      kind, recipeId, variantId, draft, exact, packages, amountMode, pkgIdx, pkgCount, pkgSplit, meal, dates, rows, guests, guestWeight, potStatus, potFree, busy, error,
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
        <ProductFinder v-model="variantId" v-model:draft="draft" autofocus kbjuPrompt />
        <span v-if="!variantId && !draft" class="tiny muted">Сначала ищем в справочнике, не нашли — в Open Food Facts. 📷 — штрихкод камерой.</span>
      </div>
      <OffDraftCard v-if="kind === 'product' && draft" :draft="draft" />
      <label v-if="kind === 'product' && (variantId || draft)" class="row small" style="gap: 8px; cursor: pointer">
        <input type="checkbox" v-model="exact">
        <span>🎯 Именно этот вариант <span class="muted">— в покупках этот бренд, а не любой бренд того же товара</span></span></label>

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
