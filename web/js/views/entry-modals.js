// Модалки записей плана/дневника: добавление (блюдо или готовый продукт) и действия с записью.
import { ref, computed, watch } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { Modal, Picker, VariantPicker, Macros } from "../components.js";
import { state, toast, toastError, variantIndex, recipeById, recipeCategoryName } from "../store.js";
import { MEALS, MEAL_LABEL, STATUS, fmt, grams, n, fmtWeekday, fmtDayMonth } from "../util.js";

export function entryName(e) {
  return e.kind === "product" ? e.product_name : e.recipe_name || `Рецепт #${e.recipe_id}`;
}

export function sourceBadge(e) {
  if (e.kind === "product") return { text: "Готовый продукт", cls: "info" };
  if (e.status === "fact") {
    return e.cooking_log_id ? { text: "Из холодильника", cls: "ok" } : { text: "Без холодильника", cls: "" };
  }
  if (e.source_status === "fridge") {
    return e.fridge_enough
      ? { text: `В холодильнике · ост. ${grams(e.fridge_available_g)}`, cls: "ok" }
      : { text: `Мало в холодильнике · ост. ${grams(e.fridge_available_g)}`, cls: "warn" };
  }
  if (e.fridge_pot_id && e.fridge_enough) return { text: `Есть кастрюля · свободно ${grams(n(e.fridge_available_g) - n(e.fridge_planned_g))}`, cls: "info" };
  if (e.fridge_pot_id) return { text: "Надо приготовить · в кастрюле не хватит", cls: "warn" };
  return { text: "Надо приготовить", cls: "warn" };
}

export const AddEntryModal = {
  components: { Modal, Picker, VariantPicker, Macros },
  props: { date: String, meal: String, days: Array },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const kind = ref("recipe");
    const recipeId = ref(null);
    const variantId = ref(null);
    const weight = ref(250);
    const people = ref(1);
    const meal = ref(props.meal || "lunch");
    const dates = ref([props.date]);
    const potStatus = ref(null);
    const busy = ref(false);
    const error = ref("");

    const recipeItems = computed(() =>
      [...state.recipes]
        .sort((a, b) => a.name.localeCompare(b.name, "ru"))
        .map((r) => ({
          id: r.id, label: r.name,
          group: recipeCategoryName.value[r.recipe_category_id] || "Без категории",
          right: `${fmt(r.calories_per_100g)} ккал/100 г`,
        }))
        .sort((a, b) => a.group.localeCompare(b.group, "ru"))
    );
    const recipe = computed(() => recipeById.value[recipeId.value]);
    const portionHint = computed(() => {
      const r = recipe.value;
      if (!r) return null;
      return n(r.estimated_cooked_weight) / Math.max(1, r.default_servings || 1);
    });
    const per100 = computed(() => {
      if (kind.value === "recipe" && recipe.value) {
        const r = recipe.value;
        return { calories: n(r.calories_per_100g), proteins: n(r.proteins_per_100g), fats: n(r.fats_per_100g), carbs: n(r.carbs_per_100g) };
      }
      const v = variantIndex.value[variantId.value];
      return v ? { calories: v.calories, proteins: v.proteins, fats: v.fats, carbs: v.carbs } : null;
    });
    const portion = computed(() => {
      if (!per100.value) return null;
      const k = n(weight.value) / 100;
      const p = per100.value;
      return { calories: p.calories * k, proteins: p.proteins * k, fats: p.fats * k, carbs: p.carbs * k };
    });

    watch(recipeId, (id) => {
      if (id && portionHint.value) weight.value = Math.round(portionHint.value);
    });
    watch(variantId, (id) => { if (id) weight.value = 100; });
    watch([recipeId, weight, kind, people], async () => {
      potStatus.value = null;
      if (kind.value !== "recipe" || !recipeId.value || !(n(weight.value) > 0)) return;
      try {
        // из кастрюли запись заберёт порцию на всех едоков
        potStatus.value = await api.get(`/diary/pot-status/${recipeId.value}`, { portion_g: n(weight.value) * (Number(people.value) || 1) });
      } catch { /* необязательная подсказка */ }
    });
    const potFree = computed(() => potStatus.value ? n(potStatus.value.available_g) - n(potStatus.value.planned_g) : 0);

    function toggleDate(d) {
      const i = dates.value.indexOf(d);
      if (i >= 0) { if (dates.value.length > 1) dates.value.splice(i, 1); }
      else dates.value.push(d);
    }

    async function save() {
      error.value = "";
      const body = {
        meal_type: meal.value,
        weight_g: n(weight.value),
        servings_multiplier: Number(people.value) || 1,
      };
      if (kind.value === "recipe") {
        if (!recipeId.value) { error.value = "Выберите блюдо"; return; }
        body.recipe_id = recipeId.value;
      } else {
        if (!variantId.value) { error.value = "Выберите продукт"; return; }
        body.variant_id = variantId.value;
      }
      busy.value = true;
      try {
        for (const d of [...dates.value].sort()) {
          await api.post("/diary/", { ...body, date_day: d });
        }
        toast(dates.value.length > 1 ? `Добавлено в ${dates.value.length} дн.` : "Добавлено в план");
        emit("saved");
      } catch (e) {
        error.value = e.message;
      } finally {
        busy.value = false;
      }
    }

    return {
      kind, recipeId, variantId, weight, people, meal, dates, potStatus, busy, error,
      recipeItems, recipe, portionHint, portion, potFree, MEALS, toggleDate, save,
      fmt, grams, fmtWeekday, fmtDayMonth, n,
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
      </label>
      <label class="field" v-else><span>Продукт из магазина</span>
        <VariantPicker v-model="variantId" placeholder="Йогурт, хлеб, сыр…" autofocus />
        <span class="tiny">Нет нужного? Добавьте его в «Продукты» — с КБЖУ с упаковки.</span>
      </label>

      <div class="grid-2">
        <label class="field"><span>Порция на человека, г</span>
          <input type="number" min="1" max="999.9" step="any" v-model="weight">
          <span v-if="kind === 'recipe' && portionHint" class="tiny">Стандартная порция ≈ {{ fmt(portionHint) }} г</span>
        </label>
        <label class="field"><span>Сколько человек едят</span>
          <select v-model.number="people"><option v-for="i in 10" :key="i" :value="i">{{ i }}</option></select>
          <span class="tiny">Все едят такую же порцию: столько уйдёт из кастрюли и в покупки. КБЖУ — на вас</span>
        </label>
      </div>

      <div class="small" v-if="portion"><span class="muted">Ваша порция: </span><Macros :m="portion" /></div>

      <div v-if="potStatus && potStatus.has_active_pot" class="alert" :class="potFree >= n(weight) * people ? 'info' : 'warn'">
        В холодильнике есть это блюдо: осталось {{ grams(potStatus.available_g) }},
        из них уже запланировано {{ grams(potStatus.planned_g) }}.
        <template v-if="potFree >= n(weight) * people">Свободного хватает: {{ grams(n(weight) * people) }} возьмём из кастрюли, при «Съедено» она спишется.</template>
        <template v-else>Свободно только {{ grams(Math.max(0, potFree)) }} — блюдо попадёт в список покупок как «надо приготовить».</template>
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

export const EntryModal = {
  components: { Modal, Macros },
  props: { entry: Object },
  emits: ["close", "saved"],
  setup(props, { emit }) {
    const weight = ref(n(props.entry.weight_g));
    const people = ref(props.entry.servings_multiplier || 1);
    const busy = ref(false);
    const error = ref("");
    const e = computed(() => props.entry);
    const st = computed(() => STATUS[e.value.status] || { label: e.value.status });
    const badge = computed(() => sourceBadge(e.value));

    async function run(fn, msg) {
      error.value = "";
      busy.value = true;
      try {
        await fn();
        if (msg) toast(msg);
        emit("saved");
      } catch (err) {
        error.value = err.message;
      } finally {
        busy.value = false;
      }
    }
    const peopleChanged = computed(() => Number(people.value) !== (e.value.servings_multiplier || 1));
    const eat = () => run(async () => {
      // сначала фиксируем число едоков — от него зависит, сколько спишется из кастрюли
      if (peopleChanged.value) await api.patch(`/diary/${e.value.id}/weight`, { weight_g: n(e.value.weight_g), servings_multiplier: Number(people.value) });
      await api.post(`/diary/${e.value.id}/eat`, { weight_g: n(weight.value) });
    }, "Отмечено как съеденное");
    const saveWeight = () => run(() => api.patch(`/diary/${e.value.id}/weight`, { weight_g: n(weight.value), servings_multiplier: Number(people.value) }), "Сохранено");
    const fromPot = computed(() => e.value.kind === "recipe" && (e.value.cooking_log_id || e.value.fridge_pot_id));
    const detach = () => run(() => api.post(`/diary/${e.value.id}/detach`), "Отвязано от холодильника");
    const remove = () => {
      const extra = e.value.status === "fact" && e.value.cooking_log_id ? "\nВес вернётся в кастрюлю холодильника." : "";
      if (!confirm(`Удалить «${entryName(e.value)}»?${extra}`)) return;
      run(() => api.del(`/diary/${e.value.id}`), "Удалено");
    };
    return { e, weight, people, busy, error, st, badge, eat, saveWeight, detach, remove, fromPot, entryName, MEAL_LABEL, grams, fmtWeekday, fmtDayMonth, n };
  },
  template: `
    <Modal :title="entryName(e)" @close="$emit('close')">
      <div class="row">
        <span class="badge" :class="st.cls">{{ st.icon }} {{ st.label }}</span>
        <span class="badge" :class="badge.cls">{{ badge.text }}</span>
        <span class="muted small">{{ MEAL_LABEL[e.meal_type] }} · {{ fmtWeekday(e.date_day) }} {{ fmtDayMonth(e.date_day) }}</span>
      </div>
      <div><Macros :m="e" :digits="1" /> <span class="muted small">на {{ grams(e.weight_g) }}</span></div>
      <div class="grid-2">
        <label class="field"><span>{{ e.status === 'fact' ? 'Съедено на человека, г' : 'Порция на человека, г' }}</span>
          <input type="number" min="1" max="999.9" step="any" v-model="weight" @keydown.enter="e.status === 'fact' ? saveWeight() : eat()">
        </label>
        <label class="field"><span>Сколько человек едят</span>
          <select v-model.number="people"><option v-for="i in 10" :key="i" :value="i">{{ i }}</option></select>
        </label>
      </div>
      <div class="muted small" v-if="fromPot && people > 1">Из кастрюли уйдёт {{ grams(n(weight) * people) }} — порция на {{ people }} чел.</div>
      <div v-if="error" class="alert error">{{ error }}</div>
      <template #foot>
        <button class="danger" :disabled="busy" @click="remove">Удалить</button>
        <button v-if="e.status === 'fact' && e.cooking_log_id" :disabled="busy" @click="detach"
                title="Съедено, но не из этой кастрюли — вес в неё не возвращается">Было без холодильника</button>
        <span class="grow"></span>
        <button :disabled="busy" @click="saveWeight">Сохранить вес</button>
        <button v-if="e.status !== 'fact'" class="primary" :disabled="busy" @click="eat">✓ Съедено</button>
      </template>
    </Modal>`,
};
