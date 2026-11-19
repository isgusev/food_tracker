<script setup lang="ts">
// Семья: кто ест (цели каждого), приглашения, общие настройки (допуск по весу, планировщик), оформление, выход.
import { onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { api, ok, type Schemas } from "../../api/client";
import { loadRecipes } from "../../catalog";
import MemberCard from "../../components/family/MemberCard.vue";
import PlannerSettings from "../../components/family/PlannerSettings.vue";
import { loadSession, logout, session, toast, toastError } from "../../session";
import { local } from "../../util";

const router = useRouter();
const hh = () => session.household!;
const busy = ref(false);
async function run(fn: () => Promise<Schemas["HouseholdResponse"]>, msg: string) {
  busy.value = true;
  try { session.household = await fn(); toast(msg); return true; }
  catch (e) { toastError(e); return false; } finally { busy.value = false; }
}

// ---- люди
const openId = ref<number | null>(null);
const newName = ref("");
const newKcal = ref<number | string>("");
async function addMember() {
  if (!newName.value.trim()) return;
  if (await run(() => ok(api.POST("/api/v1/household/members", { body: {
    name: newName.value.trim(), targets: { calories: newKcal.value === "" ? null : Number(newKcal.value) } } as Schemas["MemberCreate"] })), "Член семьи добавлен")) {
    newName.value = ""; newKcal.value = "";
  }
}

// ---- семья и код
const name = ref(session.household?.name || "");
watch(() => session.household?.name, (v) => { name.value = v || ""; });
const rename = () => run(() => ok(api.PATCH("/api/v1/household", { body: { name: name.value.trim() } })), "Название сохранено");
async function copy(text: string, msg: string) {
  try { await navigator.clipboard.writeText(text); toast(msg); } catch { toast(text); }
}
function newCode() {
  if (!confirm("Выпустить новый код? Старый перестанет работать.")) return;
  run(() => ok(api.POST("/api/v1/household/invite-code")), "Новый код готов");
}

// ---- приглашения в приложение (регистрация — пока в старом интерфейсе)
const invites = ref<Schemas["InviteResponse"][]>([]);
const intoFamily = ref(true);
const loadInvites = () => ok(api.GET("/api/v1/household/registration-invites")).then((r) => { invites.value = r; }).catch(() => {});
onMounted(loadInvites);
const inviteLink = (code: string) => `${location.origin}/app/#/register?code=${code}`;
async function createInvite() {
  try {
    const inv = await ok(api.POST("/api/v1/household/registration-invites", { body: { into_household: intoFamily.value } }));
    await loadInvites();
    await copy(inviteLink(inv.code), "Ссылка-приглашение скопирована");
  } catch (e) { toastError(e); }
}
async function revoke(inv: Schemas["InviteResponse"]) {
  if (!confirm(`Отозвать приглашение ${inv.code}?`)) return;
  try {
    const r = await api.DELETE("/api/v1/household/registration-invites/{invite_id}", { params: { path: { invite_id: inv.id } } });
    if (!r.response.ok) await ok(Promise.resolve(r));
    await loadInvites();
  } catch (e) { toastError(e); }
}

// ---- допуск по весу
const tolerance = ref<number | string>(session.household?.portion_tolerance ?? 15);
watch(() => session.household?.portion_tolerance, (v) => { tolerance.value = v ?? 15; });
const tolOk = () => tolerance.value !== "" && Number(tolerance.value) >= 0 && Number(tolerance.value) <= 30;
const saveTolerance = () => run(() => ok(api.PATCH("/api/v1/household", { body: { portion_tolerance: Math.round(Number(tolerance.value)) } })), "Допуск сохранён");

// ---- вступить в другую семью
const joinCode = ref("");
async function join() {
  if (!joinCode.value.trim()) return;
  if (!confirm("Вступить в другую семью? Ваши рецепты, холодильник, план и члены семьи без аккаунта переедут туда.")) return;
  if (await run(() => ok(api.POST("/api/v1/household/join", { body: { invite_code: joinCode.value.trim().toUpperCase() } })), "Вы в новой семье")) {
    joinCode.value = "";
    await Promise.all([loadSession(), loadRecipes()]);
  }
}

// ---- оформление (та же настройка, что в старом интерфейсе)
type Theme = "auto" | "light" | "dark";
const theme = ref<Theme>(local.get<Theme>("ft.theme", "auto"));
function setTheme(t: Theme) {
  theme.value = t;
  local.set("ft.theme", t);
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}
function signOut() { logout(); router.replace("/login"); }
const until = (iso: string) => new Date(iso).toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
</script>

<template>
  <div v-if="session.household" class="family">
    <header class="head">
      <h1 class="display">Семья</h1>
      <button class="text danger" @click="signOut">Выйти ({{ session.user?.username }})</button>
    </header>

    <!-- главный контейнер — люди: для них и планируем -->
    <section class="pot people">
      <h2>Кто ест</h2>
      <div class="list">
        <MemberCard v-for="m in hh().members" :key="m.id" :member="m" :open="openId === m.id" @toggle="openId = openId === m.id ? null : m.id" />
      </div>
      <div class="add">
        <input v-model="newName" placeholder="Имя (например, Маша)" aria-label="Имя нового члена семьи" @keydown.enter="addMember">
        <input v-model="newKcal" type="number" min="0" inputmode="numeric" placeholder="Ккал/день" aria-label="Ккал в день" class="kc" @keydown.enter="addMember">
        <button class="fill small" :disabled="busy || !newName.trim()" @click="addMember">Добавить</button>
      </div>
      <p class="tiny muted">Ребёнок, бабушка — все, кому планируете порции. Остальные цели — в карточке после добавления.</p>
    </section>

    <section class="card">
      <h2>Семья и приглашения</h2>
      <div class="inline">
        <input v-model="name" aria-label="Название семьи" class="nm">
        <button class="small" :disabled="busy || !name.trim() || name.trim() === hh().name" @click="rename">Сохранить</button>
      </div>
      <p class="small muted">Рецепты, холодильник, план и список покупок — общие для всей семьи. КБЖУ у каждого свои.</p>
      <div class="code inset">
        <span class="small">Код семьи</span>
        <b class="display codev">{{ hh().invite_code }}</b>
        <span class="grow"></span>
        <button class="small" @click="copy(hh().invite_code, 'Код скопирован')">Копировать</button>
        <button class="text small" :disabled="busy" @click="newCode">Новый код</button>
      </div>
      <p class="tiny muted">У кого уже есть аккаунт — вводит этот код в «Вступить в другую семью» и видит всё то же, что и вы.</p>

      <h3>Пригласить в приложение</h3>
      <div class="inline wrap">
        <label class="check"><input v-model="intoFamily" type="checkbox"><span>сразу в нашу семью</span></label>
        <button class="small" @click="createInvite">Создать приглашение</button>
      </div>
      <p class="tiny muted">Регистрация только по приглашению. Код одноразовый, действует 7 дней; ссылка копируется сразу — отправьте её в мессенджер.</p>
      <div v-if="invites.length" class="invites">
        <div v-for="inv in invites" :key="inv.id" class="inv">
          <span class="grow"><b class="mono">{{ inv.code }}</b> <span class="badge">{{ inv.into_household ? "в семью" : "своя семья" }}</span>
            <span class="tiny muted block">{{ inv.used ? `использовано: ${inv.used_by}` : `действует до ${until(inv.expires_at)}` }}</span></span>
          <template v-if="!inv.used">
            <button class="text small" @click="copy(inviteLink(inv.code), 'Ссылка скопирована')">Ссылка</button>
            <button class="text x" :aria-label="'Отозвать ' + inv.code" title="Отозвать" @click="revoke(inv)">✕</button>
          </template>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>Допуск по весу</h2>
      <div class="inline">
        <input v-model="tolerance" type="number" min="0" max="30" step="1" inputmode="numeric" class="tol" aria-label="Допуск, %"><span>%</span>
        <button class="small" :disabled="busy || !tolOk() || Number(tolerance) === hh().portion_tolerance" @click="saveTolerance">Сохранить</button>
      </div>
      <p class="tiny muted">Блюдо вышло меньше плана не больше чем на столько — оно всё равно «в холодильнике», а несъеденные порции
        уменьшаются пропорционально. В покупках — не берём лишнюю упаковку ради недобора в эти проценты (400 г при пачке 360 г —
        одна пачка). 0 — строго по плану.</p>
    </section>

    <section class="card">
      <h2>Планировщик</h2>
      <PlannerSettings />
    </section>

    <section class="card">
      <h2>Оформление</h2>
      <div class="seg" role="radiogroup" aria-label="Тема">
        <button v-for="t in (['auto', 'light', 'dark'] as const)" :key="t" role="radio" :aria-checked="theme === t" :class="{ on: theme === t }" @click="setTheme(t)">
          {{ { auto: "Как в системе", light: "Светлая", dark: "Тёмная" }[t] }}</button>
      </div>
    </section>

    <section class="card">
      <h2>Вступить в другую семью</h2>
      <div class="inline">
        <input v-model="joinCode" placeholder="Код семьи" aria-label="Код другой семьи" class="nm up" @keydown.enter="join">
        <button class="small" :disabled="busy || !joinCode.trim()" @click="join">Вступить</button>
      </div>
      <p class="tiny muted">Ваши рецепты, кастрюли, запасы и план переедут в ту семью.</p>
    </section>
  </div>
</template>

<style scoped>
.family { display: flex; flex-direction: column; gap: 14px; max-width: 760px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
h1 { font-size: 32px; color: var(--rim); }
h2 { font-size: 18px; }
h3 { font-size: 16px; margin-top: 6px; }
p { margin: 0; }
.grow { flex: 1; min-width: 0; }
.block { display: block; }
.danger { color: var(--tomato); }
.people { padding: 14px 0 16px; display: flex; flex-direction: column; gap: 10px; }
.people > h2, .people > .add, .people > p { margin: 0 16px; }
.list { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.add { display: flex; flex-wrap: wrap; gap: 8px; }
.add input { flex: 1 1 180px; width: auto; }
.add .kc { flex: 0 1 130px; }
.card { display: flex; flex-direction: column; gap: 10px; padding: 14px 16px; border-radius: var(--r-pot); background: var(--enamel); border: 1.5px solid var(--line); }
.inline { display: flex; align-items: center; gap: 8px; }
.inline.wrap { flex-wrap: wrap; }
.nm { max-width: 300px; }
.up { text-transform: uppercase; }
.tol { width: 90px; }
.code { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 14px; }
.codev { font-size: 22px; letter-spacing: 0.12em; color: var(--rim); }
.mono { letter-spacing: 0.08em; }
.check { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.check input { width: 20px; height: 20px; min-height: 0; margin: 0; accent-color: var(--rim); }
.invites { display: flex; flex-direction: column; }
.inv { display: flex; align-items: center; gap: 6px; padding: 6px 0; border-top: 1px solid var(--line); }
.inv:first-child { border-top: 0; }
.badge { font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); }
.x { min-width: 40px; padding: 0; color: var(--muted); }
button.small { min-height: 40px; padding: 0 14px; font-size: 14px; }
.seg { display: inline-flex; flex-wrap: wrap; gap: 4px; padding: 3px; border-radius: 999px; background: var(--enamel-2); align-self: flex-start; }
.seg button { min-height: 38px; border: 0; padding: 0 14px; color: var(--ink); font-weight: 500; }
.seg button.on { background: var(--rim); color: var(--on-fill); font-weight: 700; }
</style>
