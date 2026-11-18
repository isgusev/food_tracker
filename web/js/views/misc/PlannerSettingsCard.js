import { ref, reactive, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { state, loadHousehold, loadRecipes, toast } from "../../store.js";
import { MEALS, fmt, local, n } from "../../util.js";

// «Семья → Планировщик»: настройки автоплана (docs/AUTOPLAN.md, 3.3)
export const PlannerSettingsCard = {
  setup() {
    const days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
    const meals = MEALS;
    const s = reactive({ meal_types: null, no_cook_days: [], special_days: [], max_special_per_week: 1, snack_categories: [], snack_quota: null });
    const cats = ref([]);
    onMounted(() => api.get("/products/categories").then((r) => { cats.value = r; }).catch(() => {}));
    const toggleCat = (id) => { s.snack_categories = s.snack_categories.includes(id) ? s.snack_categories.filter((x) => x !== id) : [...s.snack_categories, id]; };
    const saved = ref("");
    const busy = ref(false);
    const snapshot = () => JSON.stringify(s);
    onMounted(async () => {
      try { Object.assign(s, await api.get("/household/planner")); saved.value = snapshot(); } catch (e) { toast(e.message, "error"); }
    });
    const mealOn = (k) => !s.meal_types || s.meal_types.includes(k);
    function toggleMeal(k) {
      const cur = s.meal_types || meals.map((m) => m.key);
      const next = cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k];
      if (!next.length) return;   // хотя бы один приём
      s.meal_types = next.length === meals.length ? null : meals.map((m) => m.key).filter((x) => next.includes(x));
    }
    function toggleDay(list, i) {
      s[list] = s[list].includes(i) ? s[list].filter((x) => x !== i) : [...s[list], i].sort();
    }
    async function save() {
      busy.value = true;
      const body = { ...s, snack_quota: s.snack_quota === "" || s.snack_quota == null ? null : Number(s.snack_quota) };
      try { Object.assign(s, await api.patch("/household/planner", body)); saved.value = snapshot(); toast("Настройки планировщика сохранены"); }
      catch (e) { toast(e.message, "error"); } finally { busy.value = false; }
    }
    const dirty = computed(() => saved.value && saved.value !== snapshot());
    return { s, days, meals, mealOn, toggleMeal, toggleDay, save, busy, dirty, cats, toggleCat };
  },
  template: `
    <div class="card stack">
      <h3>Планировщик</h3>
      <div class="tiny muted">Для кнопки «✨ Предложить» в плане: что заполнять и когда не готовить.</div>
      <div class="stack tight">
        <span class="small">Какие приёмы пищи заполнять</span>
        <div class="row tight">
          <button v-for="m in meals" :key="m.key" class="sm chip" :class="{ on: mealOn(m.key) }" :aria-pressed="mealOn(m.key)" @click="toggleMeal(m.key)">{{ m.label }}</button>
        </div>
      </div>
      <div class="stack tight">
        <span class="small">Дни без готовки <span class="muted">— только остатки и заготовки из морозилки</span></span>
        <div class="row tight">
          <button v-for="(d, i) in days" :key="i" class="sm chip" :class="{ on: s.no_cook_days.includes(i) }" :aria-pressed="s.no_cook_days.includes(i)" @click="toggleDay('no_cook_days', i)">{{ d }}</button>
        </div>
      </div>
      <div class="stack tight">
        <span class="small">Дни для особых блюд <span class="muted">— не выбраны: в любой день</span></span>
        <div class="row tight">
          <button v-for="(d, i) in days" :key="i" class="sm chip" :class="{ on: s.special_days.includes(i) }" :aria-pressed="s.special_days.includes(i)" @click="toggleDay('special_days', i)">{{ d }}</button>
        </div>
      </div>
      <label class="row small">Особых блюд в неделю, не больше
        <input type="number" min="0" max="7" v-model.number="s.max_special_per_week" style="width: 70px"></label>
      <div class="stack tight">
        <span class="small">Снеки и сладкое <span class="muted">— категории продуктов; в «Покупках» и «Деньгах» видно, сколько ушло</span></span>
        <div class="row tight" v-if="cats.length">
          <button v-for="c in cats" :key="c.id" class="sm chip" :class="{ on: s.snack_categories.includes(c.id) }" :aria-pressed="s.snack_categories.includes(c.id)" @click="toggleCat(c.id)">{{ c.name }}</button>
        </div>
        <label class="row small">Квота в неделю
          <input type="number" min="0" step="50" v-model="s.snack_quota" style="width: 100px" placeholder="без квоты"> ₽</label>
        <span class="tiny muted">Сверх квоты снеки не попадают в «Обычно берём». Отдельный товар можно отметить снеком в его карточке в запасах.</span>
      </div>
      <div class="row"><button class="sm primary" :disabled="busy || !dirty" @click="save">Сохранить</button></div>
    </div>`,
};
