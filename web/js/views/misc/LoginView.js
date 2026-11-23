import { ref, reactive, computed, watch, onMounted } from "../../../vendor/vue.esm-browser.prod.js";
import { api } from "../../api.js";
import { useAction } from "../../use-action.js";
import { state, loadHousehold, loadRecipes, toast } from "../../store.js";
import { MEALS, fmt, local, n } from "../../util.js";

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
