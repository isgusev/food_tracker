<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { api, auth, ok } from "../api/client";
import { loadSession } from "../session";

const router = useRouter();
const icon = `${import.meta.env.BASE_URL}icon.svg`;
const identifier = ref("");
const password = ref("");
const busy = ref(false);
const error = ref("");

async function submit() {
  error.value = "";
  busy.value = true;
  try {
    const t = await ok(api.POST("/api/v1/auth/login", {
      body: { identifier: identifier.value.trim(), password: password.value },
      bodySerializer: (b) => new URLSearchParams(b as Record<string, string>),
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }));
    auth.set(t.access_token);
    await loadSession();
    router.replace("/today");
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
      <label>Логин или email<input v-model="identifier" autocomplete="username" required></label>
      <label>Пароль<input v-model="password" type="password" autocomplete="current-password" required></label>
      <p v-if="error" class="err small" role="alert">{{ error }}</p>
      <button class="fill" :disabled="busy">{{ busy ? "Входим…" : "Войти" }}</button>
      <a href="/app/#/register" class="small">Регистрация — в старом интерфейсе</a>
    </form>
  </div>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; padding: var(--gutter); }
.card { width: 100%; max-width: 380px; padding: 24px; display: flex; flex-direction: column; gap: 14px; }
.logo { border-radius: 14px; }
h1 { font-size: 28px; color: var(--rim); }
p { margin: -6px 0 4px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--muted); }
.err { color: var(--tomato); margin: 0; }
</style>
