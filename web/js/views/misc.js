// Вход/регистрация и страница «Семья» (члены семьи, цели КБЖУ, приглашение, тема).
import { ref, reactive, computed, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { state, loadHousehold, loadRecipes, toast } from "../store.js";
import { fmt, local, n } from "../util.js";

export const LoginView = {
  emits: ["done"],
  setup(_, { emit }) {
    // Ссылка-приглашение: …/app/#/register?code=XXXX — сразу открываем регистрацию с кодом
    const fromLink = new URLSearchParams(location.hash.split("?")[1] || "").get("code") || "";
    const mode = ref(fromLink ? "register" : "login");
    const f = ref({ identifier: "", username: "", email: "", password: "", code: fromLink });
    const cfg = ref({ registration_mode: "open", needs_first_user: false });
    onMounted(() => api.get("/auth/config").then((c) => { cfg.value = c; }).catch(() => {}));
    const busy = ref(false);
    const error = ref("");
    async function submit() {
      error.value = ""; busy.value = true;
      try {
        if (mode.value === "login") await api.login(f.value.identifier, f.value.password);
        else await api.register(f.value.username, f.value.email, f.value.password, f.value.code.trim());
        if (fromLink) history.replaceState(null, "", "#/plan");
        emit("done");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return { mode, f, cfg, busy, error, submit };
  },
  template: `
    <div class="login-wrap">
      <form class="card login-card stack" @submit.prevent="submit">
        <img src="icons/icon.svg" alt="" width="56" height="56" style="border-radius: 14px">
        <h1>ЕлиГуси</h1>
        <div class="small muted" style="margin-top: -6px">План питания, покупки и КБЖУ для всей семьи</div>
        <div class="segmented">
          <button type="button" :class="{ on: mode === 'login' }" @click="mode = 'login'">Вход</button>
          <button type="button" :class="{ on: mode === 'register' }" @click="mode = 'register'">Регистрация</button>
        </div>
        <template v-if="mode === 'login'">
          <label class="field"><span>Логин или email</span><input v-model="f.identifier" autocomplete="username" autofocus></label>
        </template>
        <template v-else>
          <label class="field"><span>Имя пользователя</span><input v-model="f.username" autocomplete="username"></label>
          <label class="field"><span>Email</span><input type="email" v-model="f.email" autocomplete="email"></label>
          <label class="field" v-if="cfg.registration_mode === 'invite'"><span>Код приглашения</span>
            <input v-model="f.code" autocomplete="off" style="text-transform: uppercase; letter-spacing: .08em">
            <span class="tiny" v-if="cfg.needs_first_user">Первая регистрация на сервере — код из переменной FIRST_INVITE_CODE.</span>
            <span class="tiny" v-else>Регистрация только по приглашению: код выдаёт тот, кто уже пользуется приложением.</span>
          </label>
          <div class="tiny muted" v-else>После регистрации вы попадёте в свою семью. Чтобы присоединиться к уже существующей — введите её код в разделе «Семья».</div>
        </template>
        <label class="field"><span>Пароль</span>
          <input type="password" v-model="f.password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"></label>
        <div v-if="error" class="alert error">{{ error }}</div>
        <button class="primary" :disabled="busy">{{ mode === 'login' ? 'Войти' : 'Создать аккаунт' }}</button>
      </form>
    </div>`,
};

const TARGET_KEYS = [
  { k: "calories", label: "Ккал" },
  { k: "proteins", label: "Белки, г" },
  { k: "fats", label: "Жиры, г" },
  { k: "carbs", label: "Углеводы, г" },
];
const emptyToNull = (v) => (v === "" || v == null ? null : n(v));

// Расчёт целей: МР 2.3.1.0253-21 (Миффлин–Сан Жеор × КФА) + поправка на цель (app/services/nutrition.py)
const ACTIVITY = [
  { v: 1.4, label: "Очень низкая: сидячая работа" },
  { v: 1.6, label: "Низкая: 1–3 тренировки в нед." },
  { v: 1.9, label: "Средняя: на ногах, 3–5 трен." },
  { v: 2.2, label: "Высокая: тяжёлый труд, спорт" },
];
const GOALS = [
  { k: "lose", label: "Снижение" },
  { k: "maintain", label: "Поддержание" },
  { k: "gain", label: "Набор" },
];
const PROFILE_KEYS = ["sex", "birth_year", "height_cm", "weight_kg", "activity", "goal"];

// Карточка члена семьи: имя, цели, скрыть/вернуть
const MemberCard = {
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

export const FamilyView = {
  components: { MemberCard },
  emits: ["logout"],
  setup() {
    const hhName = ref(state.household?.name || "");
    const newMember = reactive({ name: "", calories: "" });
    const joinCode = ref("");
    const busy = ref(false);
    const theme = ref(local.get("ft.theme", "auto"));
    watch(() => state.household?.name, (v) => { hhName.value = v || ""; });

    // Приглашения на регистрацию в приложении (одноразовые коды)
    const invites = ref([]);
    const intoFamily = ref(true);
    const loadInvites = () => api.get("/household/registration-invites").then((r) => { invites.value = r; }).catch(() => {});
    onMounted(loadInvites);
    const inviteLink = (code) => `${location.origin}${location.pathname}#/register?code=${code}`;
    async function createInvite() {
      try {
        const inv = await api.post("/household/registration-invites", { into_household: intoFamily.value });
        await loadInvites();
        try { await navigator.clipboard.writeText(inviteLink(inv.code)); toast("Ссылка-приглашение скопирована"); }
        catch { toast("Приглашение создано"); }
      } catch (e) { toast(e.message, "error"); }
    }
    async function revokeInvite(inv) {
      try { await api.del(`/household/registration-invites/${inv.id}`); await loadInvites(); } catch (e) { toast(e.message, "error"); }
    }
    async function copyLink(inv) {
      try { await navigator.clipboard.writeText(inviteLink(inv.code)); toast("Ссылка скопирована"); } catch { toast(inv.code); }
    }

    async function run(fn, msg) {
      busy.value = true;
      try { state.household = await fn(); if (msg) toast(msg); }
      catch (e) { toast(e.message, "error"); }
      finally { busy.value = false; }
    }
    const rename = () => run(() => api.patch("/household", { name: hhName.value }), "Название сохранено");
    const newCode = () => {
      if (!confirm("Выпустить новый код? Старый перестанет работать.")) return;
      run(() => api.post("/household/invite-code"), "Новый код готов");
    };
    async function copyCode() {
      try { await navigator.clipboard.writeText(state.household.invite_code); toast("Код скопирован"); }
      catch { toast("Не удалось скопировать", "error"); }
    }
    async function addMember() {
      if (!newMember.name.trim()) return;
      await run(() => api.post("/household/members", {
        name: newMember.name.trim(),
        targets: { calories: emptyToNull(newMember.calories) },
      }), "Член семьи добавлен");
      newMember.name = ""; newMember.calories = "";
    }
    async function join() {
      if (!joinCode.value.trim()) return;
      if (!confirm("Вступить в другую семью? Ваши рецепты, холодильник, план и члены семьи без аккаунта переедут туда.")) return;
      await run(() => api.post("/household/join", { invite_code: joinCode.value.trim() }), "Вы в новой семье");
      joinCode.value = "";
      await Promise.all([loadHousehold(), loadRecipes()]);
    }
    function setTheme(v) {
      theme.value = v;
      local.set("ft.theme", v);
      if (v === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", v);
    }
    return { state, hhName, newMember, joinCode, busy, theme, rename, newCode, copyCode, addMember, join, setTheme, fmt,
      invites, intoFamily, createInvite, revokeInvite, copyLink, inviteLink };
  },
  template: `
    <div class="stack" style="max-width: 760px" v-if="state.household">
      <div class="page-head" style="margin: 0">
        <h1>Семья</h1>
        <button class="danger" @click="$emit('logout')">Выйти ({{ state.user?.username }})</button>
      </div>

      <div class="card stack">
        <div class="row">
          <input v-model="hhName" style="max-width: 280px; font-weight: 600">
          <button class="sm" :disabled="busy || hhName === state.household.name" @click="rename">Сохранить название</button>
        </div>
        <div class="small muted">Рецепты, холодильник, план и список покупок — общие для всей семьи. КБЖУ считаются у каждого свои.</div>
        <div class="row">
          <span class="small">Код приглашения:</span>
          <b class="num" style="font-size: 18px; letter-spacing: .12em">{{ state.household.invite_code }}</b>
          <button class="sm" @click="copyCode">Копировать</button>
          <button class="sm ghost" :disabled="busy" @click="newCode">Новый код</button>
        </div>
        <div class="tiny muted">Второй взрослый регистрируется, открывает «Семья» и вводит этот код — и видит всё то же, что и вы.</div>
      </div>

      <h2>Кто ест</h2>
      <MemberCard v-for="m in state.household.members" :key="m.id" :member="m" />

      <div class="card stack">
        <h3>Добавить члена семьи без аккаунта</h3>
        <div class="row">
          <input v-model="newMember.name" placeholder="Имя (например, Маша)" style="max-width: 240px" @keydown.enter="addMember">
          <input type="number" min="0" v-model="newMember.calories" placeholder="Ккал/день" style="width: 120px">
          <button class="primary sm" :disabled="busy || !newMember.name.trim()" @click="addMember">Добавить</button>
        </div>
        <div class="tiny muted">Ребёнок, бабушка — все, кому планируете порции. Остальные цели задайте в карточке после добавления.</div>
      </div>

      <div class="card stack">
        <h3>Пригласить в приложение</h3>
        <div class="row">
          <label class="row small" style="gap: 6px; cursor: pointer"><input type="checkbox" v-model="intoFamily"> сразу в нашу семью</label>
          <button class="sm primary" @click="createInvite">Создать приглашение</button>
        </div>
        <div class="tiny muted">Регистрация только по приглашению. Код одноразовый, действует 7 дней; ссылка копируется сразу — отправьте её в мессенджер.</div>
        <div v-if="invites.length" class="card flush">
          <div v-for="inv in invites" :key="inv.id" class="list-item">
            <div class="grow">
              <b class="num" style="letter-spacing: .08em">{{ inv.code }}</b>
              <span class="badge" style="margin-left: 6px">{{ inv.into_household ? 'в семью' : 'своя семья' }}</span>
              <div class="tiny muted">
                <template v-if="inv.used">использовано: {{ inv.used_by }}</template>
                <template v-else>действует до {{ new Date(inv.expires_at).toLocaleDateString('ru-RU') }}</template>
              </div>
            </div>
            <template v-if="!inv.used">
              <button class="sm" @click="copyLink(inv)">Ссылка</button>
              <button class="sm ghost" @click="revokeInvite(inv)" title="Отозвать">✕</button>
            </template>
          </div>
        </div>
      </div>

      <div class="card stack">
        <h3>Вступить в другую семью</h3>
        <div class="row">
          <input v-model="joinCode" placeholder="Код приглашения" style="max-width: 200px; text-transform: uppercase" @keydown.enter="join">
          <button class="sm" :disabled="busy || !joinCode.trim()" @click="join">Вступить</button>
        </div>
        <div class="tiny muted">Ваши рецепты, кастрюли и план переедут в ту семью.</div>
      </div>

      <div class="card stack">
        <h3>Оформление</h3>
        <div class="segmented">
          <button :class="{ on: theme === 'auto' }" @click="setTheme('auto')">Как в системе</button>
          <button :class="{ on: theme === 'light' }" @click="setTheme('light')">Светлая</button>
          <button :class="{ on: theme === 'dark' }" @click="setTheme('dark')">Тёмная</button>
        </div>
      </div>
    </div>`,
};
