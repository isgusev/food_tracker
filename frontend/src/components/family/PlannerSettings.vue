<script setup lang="ts">
// Настройки «✨ Предложить»: какие приёмы пищи заполнять, дни без готовки и для особых блюд, снеки и их квота.
import { computed, onMounted, reactive, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { catalog, loadProducts } from "../../catalog";
import { toast, toastError } from "../../session";
import { MEALS } from "../../util";

const DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
type S = Omit<Schemas["PlannerSettingsOut"], "snack_quota"> & { snack_quota: number | string | null };
const s = reactive<S>({ meal_types: null, no_cook_days: [], special_days: [], max_special_per_week: 1, snack_categories: [], snack_quota: null });
const saved = ref("");
const busy = ref(false);
const snapshot = () => JSON.stringify(s);
onMounted(async () => {
  if (!catalog.loaded.products) loadProducts().catch(() => {});
  try { Object.assign(s, await ok(api.GET("/api/v1/household/planner"))); saved.value = snapshot(); } catch (e) { toastError(e); }
});
const dirty = computed(() => !!saved.value && saved.value !== snapshot());

const mealOn = (k: string) => !s.meal_types || s.meal_types.includes(k);
function toggleMeal(k: string) {
  const all = MEALS.map((m) => m.key as string);
  const cur = s.meal_types || all;
  const next = cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k];
  if (!next.length) { toast("Хотя бы один приём пищи", "error"); return; }
  s.meal_types = next.length === all.length ? null : all.filter((x) => next.includes(x));
}
function toggleDay(list: "no_cook_days" | "special_days", i: number) {
  const cur = s[list] ?? [];
  s[list] = cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i].sort();
}
function toggleCat(id: number) {
  const cur = s.snack_categories ?? [];
  s.snack_categories = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
}
async function save() {
  busy.value = true;
  const body = { ...s, snack_quota: s.snack_quota === "" || s.snack_quota == null ? null : Number(s.snack_quota) } as Schemas["PlannerSettingsUpdate"];
  try {
    Object.assign(s, await ok(api.PATCH("/api/v1/household/planner", { body })));
    saved.value = snapshot();
    toast("Настройки планировщика сохранены");
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
const cats = computed(() => [...catalog.productCategories].sort((a, b) => a.name.localeCompare(b.name, "ru")));
</script>

<template>
  <div class="planner">
    <p class="tiny muted">Для «✨ Предложить» в плане: что заполнять и когда не готовить.</p>
    <div class="grp"><span class="small">Какие приёмы пищи заполнять</span>
      <div class="chips"><button v-for="m in MEALS" :key="m.key" class="chip" :class="{ on: mealOn(m.key) }" :aria-pressed="mealOn(m.key)" @click="toggleMeal(m.key)">{{ m.label }}</button></div></div>
    <div class="grp"><span class="small">Дни без готовки <span class="muted">— только остатки и заготовки</span></span>
      <div class="chips"><button v-for="(d, i) in DAYS" :key="i" class="chip day" :class="{ on: s.no_cook_days?.includes(i) }" :aria-pressed="!!s.no_cook_days?.includes(i)" @click="toggleDay('no_cook_days', i)">{{ d }}</button></div></div>
    <div class="grp"><span class="small">Дни для особых блюд <span class="muted">— не выбраны: в любой день</span></span>
      <div class="chips"><button v-for="(d, i) in DAYS" :key="i" class="chip day" :class="{ on: s.special_days?.includes(i) }" :aria-pressed="!!s.special_days?.includes(i)" @click="toggleDay('special_days', i)">{{ d }}</button></div></div>
    <label class="inline small">Особых блюд в неделю, не больше
      <input v-model.number="s.max_special_per_week" type="number" min="0" max="7" inputmode="numeric" class="n"></label>
    <div class="grp"><span class="small">Снеки и сладкое <span class="muted">— категории продуктов; в «Покупках» и «Деньгах» видно, сколько ушло</span></span>
      <div v-if="cats.length" class="chips"><button v-for="c in cats" :key="c.id" class="chip" :class="{ on: s.snack_categories?.includes(c.id) }" :aria-pressed="!!s.snack_categories?.includes(c.id)" @click="toggleCat(c.id)">{{ c.name }}</button></div>
      <label class="inline small">Квота в неделю <input v-model="s.snack_quota" type="number" min="0" step="50" inputmode="numeric" class="q" placeholder="без квоты"> ₽</label>
      <span class="tiny muted">Сверх квоты снеки не попадают в «Обычно берём». Отдельный товар можно отметить снеком в его карточке в запасах.</span></div>
    <div><button class="fill small" :disabled="busy || !dirty" @click="save">Сохранить</button></div>
  </div>
</template>

<style scoped>
.planner { display: flex; flex-direction: column; gap: 12px; }
p { margin: 0; }
.grp { display: flex; flex-direction: column; gap: 6px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { min-height: 38px; padding: 0 14px; font-size: 14px; font-weight: 500; border-color: var(--line); color: var(--ink); background: var(--enamel); }
.chip.day { min-width: 48px; padding: 0 10px; }
.chip.on { background: var(--rim); border-color: var(--rim); color: var(--on-fill); }
.inline { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.n { width: 72px; }
.q { width: 120px; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
</style>
