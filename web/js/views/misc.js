// Вход/регистрация и профиль (личные цели КБЖУ, тема).
import { ref } from "../../vendor/vue.esm-browser.prod.js";
import { api } from "../api.js";
import { state, getTargets, setTargets, toast } from "../store.js";
import { local, n } from "../util.js";

export const LoginView = {
  emits: ["done"],
  setup(_, { emit }) {
    const mode = ref("login");
    const f = ref({ identifier: "", username: "", email: "", password: "" });
    const busy = ref(false);
    const error = ref("");
    async function submit() {
      error.value = ""; busy.value = true;
      try {
        if (mode.value === "login") await api.login(f.value.identifier, f.value.password);
        else await api.register(f.value.username, f.value.email, f.value.password);
        emit("done");
      } catch (e) { error.value = e.message; } finally { busy.value = false; }
    }
    return { mode, f, busy, error, submit };
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
        </template>
        <label class="field"><span>Пароль</span>
          <input type="password" v-model="f.password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"></label>
        <div v-if="error" class="alert error">{{ error }}</div>
        <button class="primary" :disabled="busy">{{ mode === 'login' ? 'Войти' : 'Создать аккаунт' }}</button>
      </form>
    </div>`,
};

export const ProfileView = {
  emits: ["logout"],
  setup() {
    const t = ref(getTargets());
    const theme = ref(local.get("ft.theme", "auto"));
    function save() {
      setTargets({ calories: n(t.value.calories), proteins: n(t.value.proteins), fats: n(t.value.fats), carbs: n(t.value.carbs) });
      toast("Цели сохранены");
    }
    function setTheme(v) {
      theme.value = v;
      local.set("ft.theme", v);
      if (v === "auto") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", v);
    }
    // Быстрый ориентир: Б 1.6 г/кг, Ж 0.9 г/кг, остальное — углеводы
    const weight = ref(75);
    function suggest() {
      const kg = n(weight.value);
      const p = Math.round(kg * 1.6), f = Math.round(kg * 0.9);
      const c = Math.max(0, Math.round((n(t.value.calories) - p * 4 - f * 9) / 4));
      t.value = { ...t.value, proteins: p, fats: f, carbs: c };
    }
    return { state, t, theme, save, setTheme, weight, suggest };
  },
  template: `
    <div class="stack" style="max-width: 640px">
      <div class="page-head" style="margin: 0"><h1>Профиль</h1>
        <button class="danger" @click="$emit('logout')">Выйти</button></div>
      <div class="card stack">
        <div><b>{{ state.user?.username }}</b> <span class="muted">· {{ state.user?.email }}</span></div>
      </div>
      <div class="card stack">
        <h2>Мои цели КБЖУ на день</h2>
        <div class="grid-4">
          <label class="field"><span>Ккал</span><input type="number" min="0" v-model="t.calories"></label>
          <label class="field"><span>Белки, г</span><input type="number" min="0" v-model="t.proteins"></label>
          <label class="field"><span>Жиры, г</span><input type="number" min="0" v-model="t.fats"></label>
          <label class="field"><span>Углеводы, г</span><input type="number" min="0" v-model="t.carbs"></label>
        </div>
        <div class="row small">
          <span class="muted">Подобрать БЖУ под калории для веса</span>
          <input type="number" min="30" max="250" v-model="weight" style="width: 80px"> <span class="muted">кг</span>
          <button class="sm" @click="suggest">Рассчитать</button>
        </div>
        <div class="tiny muted">Пока цели хранятся в этом браузере. В плане доработок — перенести их в профиль на сервере (см. docs/REVIEW.md).</div>
        <div><button class="primary" @click="save">Сохранить</button></div>
      </div>
      <div class="card stack">
        <h2>Оформление</h2>
        <div class="segmented">
          <button :class="{ on: theme === 'auto' }" @click="setTheme('auto')">Как в системе</button>
          <button :class="{ on: theme === 'light' }" @click="setTheme('light')">Светлая</button>
          <button :class="{ on: theme === 'dark' }" @click="setTheme('dark')">Тёмная</button>
        </div>
      </div>
    </div>`,
};
