import { ref, reactive, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { state, loadHousehold, loadRecipes, toast } from "../../store.js";
import { MEALS, fmt, local, n } from "../../util.js";
import { TARGET_KEYS, emptyToNull, ACTIVITY, GOALS, PROFILE_KEYS } from "./shared.js";

// Карточка члена семьи: имя, цели, скрыть/вернуть
export const MemberCard = {
  props: { member: Object },
  emits: ["saved"],
  setup(props, { emit }) {
    const f = reactive({ name: "", targets: {}, profile: {} });
    const calc = ref(null);   // последний расчёт: основной обмен, поддержание, пояснения
    function reset() {
      f.name = props.member.name;
      f.targets = Object.fromEntries(TARGET_KEYS.map(({ k }) => [k, props.member.targets[k] != null ? n(props.member.targets[k]) : ""]));
      const pr = props.member.profile || {};
      f.profile = {
        sex: pr.sex || "", birth_year: pr.birth_year ?? "", height_cm: pr.height_cm != null ? n(pr.height_cm) : "",
        weight_kg: pr.weight_kg != null ? n(pr.weight_kg) : "", activity: pr.activity != null ? n(pr.activity) : 1.6,
        goal: pr.goal || "maintain",
      };
    }
    watch(() => props.member, reset, { immediate: true });
    const busy = ref(false);
    async function patch(body, msg) {
      busy.value = true;
      try {
        state.household = await api.patch(`/household/members/${props.member.id}`, body);
        toast(msg);
        emit("saved");
      } catch (e) { toast(e.message, "error"); } finally { busy.value = false; }
    }
    const profileBody = () => Object.fromEntries(PROFILE_KEYS.map((k) => [k, ["sex", "goal"].includes(k) ? f.profile[k] || null : emptyToNull(f.profile[k])]));
    const save = () => patch({
      name: f.name,
      targets: Object.fromEntries(TARGET_KEYS.map(({ k }) => [k, emptyToNull(f.targets[k])])),
      profile: profileBody(),
    }, "Сохранено");
    const toggle = () => patch({ is_active: !props.member.is_active }, props.member.is_active ? "Скрыт из планирования" : "Снова в планировании");
    const calcError = ref("");
    async function suggest() {
      calcError.value = "";
      const pr = f.profile;
      if (!pr.sex || !pr.birth_year || !pr.height_cm || !pr.weight_kg) { calcError.value = "Укажите пол, год рождения, рост и вес"; return; }
      try {
        calc.value = await api.post("/household/targets/calc", profileBody());
        f.targets = Object.fromEntries(TARGET_KEYS.map(({ k }) => [k, n(calc.value.targets[k])]));
      } catch (e) { calc.value = null; calcError.value = e.message; }
    }
    const goalNote = computed(() => {
      if (!calc.value) return "";
      const g = f.profile.goal;
      return g === "lose" ? "−15 % к поддержанию, белок 1,6 г/кг" : g === "gain" ? "+10 % к поддержанию, белок 1,6 г/кг" : "белок 12–14 % калорий";
    });
    const hasProfile = computed(() => PROFILE_KEYS.some((k) => props.member.profile?.[k] != null));
    return { f, busy, save, toggle, suggest, calc, calcError, goalNote, hasProfile, TARGET_KEYS, ACTIVITY, GOALS, fmt };
  },
  template: `
    <div class="card stack" :style="{ opacity: member.is_active ? 1 : .6 }">
      <div class="row between">
        <div class="row">
          <input v-model="f.name" style="max-width: 200px; font-weight: 600">
          <span v-if="member.is_me" class="badge ok">это вы</span>
          <span v-else-if="member.user_id" class="badge info">аккаунт @{{ member.username }}</span>
          <span v-else class="badge">без аккаунта</span>
          <span v-if="!member.is_active" class="badge warn">скрыт</span>
        </div>
        <button v-if="!member.user_id" class="sm ghost" :disabled="busy" @click="toggle">{{ member.is_active ? 'Скрыть' : 'Вернуть' }}</button>
      </div>
      <div class="grid-4">
        <label v-for="t in TARGET_KEYS" :key="t.k" class="field"><span>{{ t.label }}</span>
          <input type="number" min="0" v-model="f.targets[t.k]" placeholder="—"></label>
      </div>
      <details :open="!hasProfile">
        <summary class="small" style="cursor: pointer">Рассчитать цели по росту, весу и цели</summary>
        <div class="stack tight" style="margin-top: 8px">
          <div class="segmented" role="group" aria-label="Цель">
            <button v-for="g in GOALS" :key="g.k" :class="{ on: f.profile.goal === g.k }" @click="f.profile.goal = g.k">{{ g.label }}</button>
          </div>
          <div class="grid-4">
            <label class="field"><span>Пол</span>
              <select v-model="f.profile.sex"><option value="">—</option><option value="f">женский</option><option value="m">мужской</option></select></label>
            <label class="field"><span>Год рождения</span><input type="number" min="1920" max="2010" inputmode="numeric" v-model="f.profile.birth_year" placeholder="1990"></label>
            <label class="field"><span>Рост, см</span><input type="number" min="120" max="230" step="any" v-model="f.profile.height_cm" placeholder="170"></label>
            <label class="field"><span>Вес, кг</span><input type="number" min="30" max="300" step="any" v-model="f.profile.weight_kg" placeholder="70"></label>
          </div>
          <label class="field"><span>Активность</span>
            <select v-model.number="f.profile.activity"><option v-for="a in ACTIVITY" :key="a.v" :value="a.v">{{ a.label }}</option></select></label>
          <div class="row">
            <button class="sm" @click="suggest">Рассчитать</button>
            <span v-if="calcError" class="small" style="color: var(--warn)">{{ calcError }}</span>
          </div>
          <div v-if="calc" class="tiny muted">
            Основной обмен {{ fmt(calc.bmr) }} ккал · поддержание {{ fmt(calc.maintenance) }} ккал · {{ goalNote }}, жиры 30 %.
            Цифры подставлены выше — проверьте и сохраните.
            <div v-for="note in calc.notes" :key="note" style="color: var(--warn)">{{ note }}</div>
          </div>
          <div class="tiny muted">По нормам Роспотребнадзора (МР 2.3.1.0253-21, формула Миффлина–Сан Жеора); для взрослых 18+, точность ±10 %.</div>
        </div>
      </details>
      <div class="row">
        <span class="grow"></span>
        <button class="sm primary" :disabled="busy" @click="save">Сохранить</button>
      </div>
    </div>`,
};
