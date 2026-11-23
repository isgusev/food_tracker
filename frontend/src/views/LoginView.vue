<script setup lang="ts">
// Вход и регистрация. Ссылка-приглашение …#/register?code=XXXX сразу открывает регистрацию с кодом.
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, auth, ok, type Schemas } from "../api/client";
import { loadSession } from "../session";

const route = useRoute();
const router = useRouter();
const icon = `${import.meta.env.BASE_URL}icon.svg`;
const mode = computed(() => (route.path === "/register" ? "register" : "login"));
const switchTo = (m: "login" | "register") => { error.value = ""; router.replace({ path: `/${m}`, query: route.query }); };

const identifier = ref("");
const username = ref("");
const email = ref("");
const password = ref("");
const code = ref("");
// код из ссылки; следим, а не читаем один раз: экран может появиться раньше, чем разобран адрес
watch(() => route.query.code, (c) => { if (c) code.value = String(c).toUpperCase(); }, { immediate: true });
const cfg = ref<Schemas["AuthConfig"]>({ registration_mode: "open", needs_first_user: false });
onMounted(() => { api.GET("/api/v1/auth/config").then((r) => { if (r.data) cfg.value = r.data; }).catch(() => {}); });
const byInvite = computed(() => cfg.value.registration_mode === "invite");

const busy = ref(false);
const error = ref("");
const tooShort = computed(() => mode.value === "register" && password.value.length > 0 && password.value.length < 8);

async function login(id: string) {
  const t = await ok(api.POST("/api/v1/auth/login", {
    body: { identifier: id, password: password.value },
    bodySerializer: (b) => new URLSearchParams(b as Record<string, string>),
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  }));
  auth.set(t.access_token);
}

async function submit() {
  error.value = "";
  if (tooShort.value) { error.value = "Пароль — не короче 8 символов"; return; }
  busy.value = true;
  try {
    if (mode.value === "register") {
      await ok(api.POST("/api/v1/auth/register", { body: {
        username: username.value.trim(), email: email.value.trim(), password: password.value,
        invite_code: byInvite.value ? code.value.trim().toUpperCase() || null : null,
      } }));
      await login(username.value.trim());
    } else {
      await login(identifier.value.trim());
    }
    await loadSession();
    router.replace(mode.value === "register" ? "/family" : "/today");
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <div class="login">
    <form class="pot card" @submit.prevent="submit">
      <img :src="icon" alt="" width="56" height="56" class="logo">
      <h1 class="display">ЕлиГуси</h1>
      <p class="muted small">План питания, покупки и КБЖУ для всей семьи</p>
      <div class="seg" role="tablist">
        <button type="button" role="tab" :aria-selected="mode === 'login'" :class="{ on: mode === 'login' }" @click="switchTo('login')">Вход</button>
        <button type="button" role="tab" :aria-selected="mode === 'register'" :class="{ on: mode === 'register' }" @click="switchTo('register')">Регистрация</button>
      </div>

      <template v-if="mode === 'login'">
        <label>Логин или email<input v-model="identifier" autocomplete="username" required></label>
        <label>Пароль<input v-model="password" type="password" autocomplete="current-password" required></label>
      </template>
      <template v-else>
        <label v-if="byInvite">Код приглашения
          <input v-model="code" class="code" autocomplete="off" autocapitalize="characters" spellcheck="false" required>
          <span class="hint">{{ cfg.needs_first_user
            ? "Первая регистрация на сервере — код из переменной FIRST_INVITE_CODE."
            : "Регистрация только по приглашению: код выдаёт тот, кто уже пользуется приложением." }}</span>
        </label>
        <label>Имя пользователя<input v-model="username" autocomplete="username" minlength="3" maxlength="50" required></label>
        <label>Email<input v-model="email" type="email" autocomplete="email" required></label>
        <label>Пароль<input v-model="password" type="password" autocomplete="new-password" minlength="8" maxlength="72" required>
          <span class="hint" :class="{ bad: tooShort }">Не короче 8 символов</span></label>
        <p v-if="!byInvite" class="muted small">После регистрации вы попадёте в свою семью. Чтобы присоединиться к уже существующей — введите её код в разделе «Семья».</p>
      </template>

      <p v-if="error" class="err small" role="alert">{{ error }}</p>
      <button class="fill" :disabled="busy">{{ busy ? (mode === "login" ? "Входим…" : "Создаём…") : (mode === "login" ? "Войти" : "Создать аккаунт") }}</button>
    </form>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; padding: var(--gutter); }
.card { width: 100%; max-width: 380px; padding: 24px; display: flex; flex-direction: column; gap: 14px; }
.logo { border-radius: 14px; }
h1 { font-size: 28px; color: var(--rim); }
p { margin: 0; }
.card > p.muted:first-of-type { margin: -6px 0 4px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--muted); }
.hint { font-size: 12px; }
.hint.bad { color: var(--tomato); }
.code { text-transform: uppercase; letter-spacing: 0.08em; }
.err { color: var(--tomato); }
.seg { display: flex; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); }
.seg button { flex: 1; min-height: 40px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
</style>
