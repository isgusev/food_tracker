// Вход/регистрация и страница «Семья» (члены семьи, цели КБЖУ, приглашение, тема).
import { ref, reactive, watch, onMounted } from "../../vendor/vue.esm-browser.prod.js";
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
        <div style="font-size: 34px">🥗</div>
        <h1>Food Tracker</h1>
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

// Карточка члена семьи: имя, цели, скрыть/вернуть
const MemberCard = {
  props: { member: Object },
  emits: ["saved"],
  setup(props, { emit }) {
    const f = reactive({ name: "", targets: {}, weight: 70 });
    function reset() {
      f.name = props.member.name;
      f.targets = Object.fromEntries(TARGET_KEYS.map(({ k }) => [k, props.member.targets[k] != null ? n(props.member.targets[k]) : ""]));
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
    const save = () => patch({
      name: f.name,
      targets: Object.fromEntries(TARGET_KEYS.map(({ k }) => [k, emptyToNull(f.targets[k])])),
    }, "Сохранено");
    const toggle = () => patch({ is_active: !props.member.is_active }, props.member.is_active ? "Скрыт из планирования" : "Снова в планировании");
    // Ориентир: Б 1.6 г/кг, Ж 0.9 г/кг, остальное — углеводы
    function suggest() {
      const kg = n(f.weight);
      const kcal = n(f.targets.calories) || 2000;
      const p = Math.round(kg * 1.6), fat = Math.round(kg * 0.9);
      f.targets = { calories: kcal, proteins: p, fats: fat, carbs: Math.max(0, Math.round((kcal - p * 4 - fat * 9) / 4)) };
    }
    return { f, busy, save, toggle, suggest, TARGET_KEYS };
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
      <div class="row small">
        <span class="muted">БЖУ под калории для веса</span>
        <input type="number" min="10" max="250" v-model="f.weight" style="width: 72px"><span class="muted">кг</span>
        <button class="sm" @click="suggest">Рассчитать</button>
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
