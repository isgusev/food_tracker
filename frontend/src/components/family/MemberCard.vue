<script setup lang="ts">
// Член семьи: свёрнут — имя и цели одной строкой; раскрыт — имя, цели КБЖУ и расчёт по росту, весу и цели
// (МР 2.3.1.0253-21: Миффлин–Сан Жеор × КФА, снижение −15 %, набор +10 %). Расчёт только подставляет цифры.
import { computed, reactive, ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { session, toast, targetsOf } from "../../session";
import { fmt, num } from "../../util";

type Member = Schemas["MemberResponse"];
const props = defineProps<{ member: Member; open: boolean }>();
const emit = defineEmits<{ toggle: [] }>();

const TARGETS = [
  { k: "calories", label: "Ккал" }, { k: "proteins", label: "Белки, г" },
  { k: "fats", label: "Жиры, г" }, { k: "carbs", label: "Углеводы, г" },
] as const;
const ACTIVITY = [
  { v: 1.4, label: "Очень низкая: сидячая работа" },
  { v: 1.6, label: "Низкая: 1–3 тренировки в нед." },
  { v: 1.9, label: "Средняя: на ногах, 3–5 трен." },
  { v: 2.2, label: "Высокая: тяжёлый труд, спорт" },
];
const GOALS = [{ k: "lose", label: "Снижение" }, { k: "maintain", label: "Поддержание" }, { k: "gain", label: "Набор" }];
type Num = number | string;
const f = reactive({
  name: "",
  targets: { calories: "" as Num, proteins: "" as Num, fats: "" as Num, carbs: "" as Num },
  profile: { sex: "", birth_year: "" as Num, height_cm: "" as Num, weight_kg: "" as Num, activity: 1.6, goal: "maintain" },
});
const calc = ref<Schemas["TargetsCalcOut"] | null>(null);
const showCalc = ref(false);
function reset() {
  const m = props.member, t = targetsOf(m);
  f.name = m.name;
  for (const { k } of TARGETS) f.targets[k] = t[k] ?? "";
  const pr = (m.profile ?? {}) as Partial<Schemas["BodyProfile-Output"]>;
  f.profile = { sex: pr.sex || "", birth_year: pr.birth_year ?? "", height_cm: pr.height_cm != null ? num(pr.height_cm) : "",
    weight_kg: pr.weight_kg != null ? num(pr.weight_kg) : "", activity: pr.activity != null ? num(pr.activity) : 1.6, goal: pr.goal || "maintain" };
  showCalc.value = !pr.sex && !pr.birth_year && !pr.height_cm && !pr.weight_kg;
  calc.value = null;
}
watch(() => props.member, reset, { immediate: true });

const busy = ref(false);
const error = ref("");
const orNull = (v: Num) => (v === "" || v == null ? null : num(v));
const profileBody = () => ({
  sex: f.profile.sex || null, goal: f.profile.goal || null, activity: orNull(f.profile.activity),
  birth_year: orNull(f.profile.birth_year), height_cm: orNull(f.profile.height_cm), weight_kg: orNull(f.profile.weight_kg),
});
async function patch(body: Schemas["MemberUpdate"], msg: string) {
  error.value = "";
  busy.value = true;
  try {
    session.household = await ok(api.PATCH("/api/v1/household/members/{member_id}", { params: { path: { member_id: props.member.id } }, body }));
    toast(msg);
    return true;
  } catch (e) { error.value = (e as Error).message; return false; } finally { busy.value = false; }
}
async function save() {
  if (!f.name.trim()) { error.value = "Укажите имя"; return; }
  const targets = Object.fromEntries(TARGETS.map(({ k }) => [k, orNull(f.targets[k])]));
  if (await patch({ name: f.name.trim(), targets, profile: profileBody() } as Schemas["MemberUpdate"], "Сохранено")) emit("toggle");
}
const toggleActive = () => patch({ is_active: !props.member.is_active }, props.member.is_active ? "Скрыт из планирования" : "Снова в планировании");
async function suggest() {
  error.value = "";
  const p = f.profile;
  if (!p.sex || !p.birth_year || !p.height_cm || !p.weight_kg) { error.value = "Для расчёта укажите пол, год рождения, рост и вес"; return; }
  try {
    calc.value = await ok(api.POST("/api/v1/household/targets/calc", { body: profileBody() as Schemas["TargetsCalcIn"] }));
    for (const { k } of TARGETS) f.targets[k] = num((calc.value.targets as Record<string, unknown>)[k]);
  } catch (e) { calc.value = null; error.value = (e as Error).message; }
}
const goalNote = computed(() => (f.profile.goal === "lose" ? "−15 % к поддержанию, белок 1,6 г/кг"
  : f.profile.goal === "gain" ? "+10 % к поддержанию, белок 1,6 г/кг" : "белок 12–14 % калорий"));
const summary = computed(() => {
  const t = targetsOf(props.member);
  if (t.calories == null && t.proteins == null) return "цели не заданы";
  return [t.calories != null ? `${fmt(t.calories)} ккал` : "", t.proteins != null ? `Б ${fmt(t.proteins)}` : "",
    t.fats != null ? `Ж ${fmt(t.fats)}` : "", t.carbs != null ? `У ${fmt(t.carbs)}` : ""].filter(Boolean).join(" · ");
});
</script>

<template>
  <div class="member" :class="{ open, off: !member.is_active }">
    <button class="head" :aria-expanded="open" @click="emit('toggle')">
      <span class="ava" aria-hidden="true">{{ member.name.slice(0, 1).toUpperCase() }}</span>
      <span class="who">
        <span class="nm"><b>{{ member.name }}</b>
          <span v-if="member.is_me" class="badge me">это вы</span>
          <span v-else-if="member.user_id" class="badge">@{{ member.username }}</span>
          <span v-else class="badge">без аккаунта</span>
          <span v-if="!member.is_active" class="badge warn">скрыт</span></span>
        <span class="small muted">{{ summary }}</span>
      </span>
      <span class="muted" aria-hidden="true">{{ open ? "▴" : "▾" }}</span>
    </button>

    <div v-if="open" class="body">
      <label class="field"><span class="lbl">Имя</span><input v-model="f.name"></label>
      <div class="four">
        <label v-for="t in TARGETS" :key="t.k" class="field"><span class="lbl">{{ t.label }}</span>
          <input v-model="f.targets[t.k]" type="number" min="0" inputmode="numeric" placeholder="—"></label>
      </div>

      <button v-if="!showCalc" class="text small calc-open" @click="showCalc = true">Рассчитать цели по росту, весу и цели…</button>
      <section v-else class="calc">
        <div class="seg" role="radiogroup" aria-label="Цель">
          <button v-for="g in GOALS" :key="g.k" role="radio" :aria-checked="f.profile.goal === g.k" :class="{ on: f.profile.goal === g.k }"
                  @click="f.profile.goal = g.k">{{ g.label }}</button>
        </div>
        <div class="four">
          <label class="field"><span class="lbl">Пол</span>
            <select v-model="f.profile.sex"><option value="">—</option><option value="f">женский</option><option value="m">мужской</option></select></label>
          <label class="field"><span class="lbl">Год рождения</span><input v-model="f.profile.birth_year" type="number" min="1920" max="2010" inputmode="numeric" placeholder="1990"></label>
          <label class="field"><span class="lbl">Рост, см</span><input v-model="f.profile.height_cm" type="number" min="120" max="230" step="any" inputmode="decimal" placeholder="170"></label>
          <label class="field"><span class="lbl">Вес, кг</span><input v-model="f.profile.weight_kg" type="number" min="30" max="300" step="any" inputmode="decimal" placeholder="70"></label>
        </div>
        <label class="field"><span class="lbl">Активность</span>
          <select v-model.number="f.profile.activity"><option v-for="a in ACTIVITY" :key="a.v" :value="a.v">{{ a.label }}</option></select></label>
        <button class="small calc-btn" @click="suggest">Рассчитать</button>
        <p v-if="calc" class="small">Основной обмен {{ fmt(calc.bmr) }} ккал · поддержание {{ fmt(calc.maintenance) }} ккал · {{ goalNote }}, жиры 30 %.
          <b>Цифры подставлены выше — проверьте и сохраните.</b></p>
        <p v-for="n in calc?.notes ?? []" :key="n" class="small warn-t">{{ n }}</p>
        <p class="tiny muted">По нормам Роспотребнадзора (МР 2.3.1.0253-21, формула Миффлина–Сан Жеора); для взрослых 18+, точность ±10 %.</p>
      </section>

      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <div class="foot">
        <button v-if="!member.user_id" class="text small" :disabled="busy" @click="toggleActive">{{ member.is_active ? "Скрыть из планирования" : "Вернуть в планирование" }}</button>
        <span class="grow"></span>
        <button class="text small" @click="reset(); emit('toggle')">Отмена</button>
        <button class="fill small" :disabled="busy" @click="save">Сохранить</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
p { margin: 0; }
.member { border-top: 1px solid var(--line); }
.member:first-child { border-top: 0; }
.member.off .head { opacity: 0.6; }
.head { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 64px; padding: 8px 16px; border: 0; border-radius: 0;
  background: transparent; color: var(--ink); font-weight: 400; text-align: left; }
.head:hover { background: var(--rim-soft); }
.ava { flex: none; width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; background: var(--rim-soft);
  color: var(--rim); font-family: var(--font-display); font-weight: 600; font-size: 18px; }
.who { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.nm { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); }
.badge.me { background: var(--rim-soft); color: var(--rim); font-weight: 600; }
.badge.warn { background: var(--beak-soft); color: var(--cook); }
.body { display: flex; flex-direction: column; gap: 12px; padding: 4px 16px 16px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.lbl { font-size: 14px; font-weight: 600; }
.four { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.calc-open { align-self: flex-start; padding: 0 4px; }
.calc { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border-radius: var(--r-in); background: var(--enamel-2); }
.calc input, .calc select { background: var(--enamel); }
.calc-btn { align-self: flex-start; }
.seg { display: inline-flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel); align-self: flex-start; }
.seg button { min-height: 38px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
.foot { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.grow { flex: 1; }
.err, .warn-t { color: var(--tomato); }
@media (max-width: 600px) {
  .four { grid-template-columns: 1fr 1fr; }
  .seg { align-self: stretch; }
  .seg button { flex: 1; padding: 0 6px; }
}
</style>
