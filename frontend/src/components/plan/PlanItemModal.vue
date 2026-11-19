<script setup lang="ts">
// Карточка блюда плана: порции по людям («Съел» с весом, отмена, правка), едоки, перенос, удаление,
// для предложения автоплана — 📌 / 🔄 / ✓. Ошибки — в окне.
import { computed, ref } from "vue";
import { api, ok } from "../../api/client";
import { activeMembers, toast } from "../../session";
import { MEALS, MEAL_LABEL, dayMonthShort, fmt, grams, num, weekdayShort } from "../../util";
import ModalSheet from "../ModalSheet.vue";
import { canSwap, itemBadge, type Item, type Portion } from "../../plan";

const props = defineProps<{ item: Item }>();
const emit = defineEmits<{ close: [] }>();

const it = ref<Item>(props.item);
const weights = ref<Record<number, number>>({});
const resetWeights = () => { weights.value = Object.fromEntries(it.value.portions.map((p) => [p.id, num(p.weight_g)])); };
resetWeights();
const busy = ref(false);
const error = ref("");
const moveDate = ref(it.value.date_day);
const moveMeal = ref(it.value.meal_type);
const addWho = ref<string>("");
const addWeight = ref(num(it.value.portions[0]?.weight_g) || 200);

/** Действие: ответ (обновлённое блюдо) подменяет карточку; null — блюдо удалено, окно закрывается. */
async function run(fn: () => Promise<Item | null | undefined>, msg?: string, closeAfter = false) {
  error.value = "";
  busy.value = true;
  try {
    const res = await fn();
    if (res) { it.value = res; resetWeights(); }
    if (msg) toast(msg);
    if (closeAfter || res === null) emit("close");
  } catch (e) { error.value = e instanceof Error ? e.message : String(e); }
  finally { busy.value = false; }
}
const pid = (p: Portion) => ({ params: { path: { portion_id: p.id } } });
const iid = () => ({ params: { path: { item_id: it.value.id } } });

const changed = (p: Portion) => num(weights.value[p.id]) !== num(p.weight_g);
const eat = (p: Portion) => run(() => ok(api.POST("/api/v1/plan/portions/{portion_id}/eat", { ...pid(p), body: { weight_g: num(weights.value[p.id]) } })),
  `${p.member_name || "Гость"}: съедено`);
const uneat = (p: Portion) => run(() => ok(api.POST("/api/v1/plan/portions/{portion_id}/uneat", pid(p))), "Отметка снята");
const detach = (p: Portion) => run(() => ok(api.POST("/api/v1/plan/portions/{portion_id}/detach", pid(p))), "Отвязано от холодильника");
const saveWeight = (p: Portion) => run(() => ok(api.PATCH("/api/v1/plan/portions/{portion_id}", { ...pid(p), body: { weight_g: num(weights.value[p.id]) } })),
  "Порция обновлена");
async function removePortion(p: Portion) {
  const last = it.value.portions.length === 1;
  if (last && !confirm("Это последняя порция — блюдо будет удалено из плана. Продолжить?")) return;
  await run(async () => {
    const r = await api.DELETE("/api/v1/plan/portions/{portion_id}", pid(p));
    if (!r.response.ok) await ok(Promise.resolve(r));
    return r.response.status === 204 ? null : (r.data as Item);
  }, last ? "Блюдо удалено" : "Порция убрана");
}
const eatAll = () => run(() => ok(api.POST("/api/v1/plan/{item_id}/eat", iid())), "Отмечено: все поели");
const move = () => run(() => ok(api.PATCH("/api/v1/plan/{item_id}", { ...iid(), body: { date_day: moveDate.value, meal_type: moveMeal.value } })), "Перенесено");
async function removeItem() {
  const fromPot = it.value.portions.some((p) => p.is_eaten && p.eaten_from_pot_id);
  if (!confirm(`Удалить «${it.value.name}» из плана?${fromPot ? "\nСъеденное вернётся в кастрюлю." : ""}`)) return;
  await run(async () => { await ok(api.DELETE("/api/v1/plan/{item_id}", iid())); return null; }, "Удалено");
}
const missing = computed(() => activeMembers.value.filter((m) => !it.value.portions.some((p) => p.member_id === m.id)));
const addPortion = () => run(async () => {
  const r = await ok(api.POST("/api/v1/plan/{item_id}/portions", { ...iid(),
    body: { member_id: addWho.value === "guest" ? null : Number(addWho.value), weight_g: num(addWeight.value) } }));
  addWho.value = "";
  return r;
}, "Порция добавлена");
const accept = () => run(() => ok(api.POST("/api/v1/plan/{item_id}/accept", iid())), "Принято");
const pin = () => run(() => ok(api.PATCH("/api/v1/plan/{item_id}", { ...iid(), body: { pinned: !it.value.pinned } })), it.value.pinned ? "Откреплено" : "Закреплено");
const swap = () => run(() => ok(api.POST("/api/v1/plan/{item_id}/alternative", iid())), "Другой вариант");
const badge = computed(() => itemBadge(it.value));
const uneaten = computed(() => it.value.portions.filter((p) => !p.is_eaten).length);
</script>

<template>
  <ModalSheet :title="it.name" wide @close="emit('close')">
    <div class="row">
      <span class="badge" :class="badge.cls">{{ badge.text }}</span>
      <span class="small muted">{{ MEAL_LABEL[it.meal_type] }} · {{ weekdayShort(it.date_day) }} {{ dayMonthShort(it.date_day) }}</span>
      <span v-if="it.fridge_pot_id" class="small muted">· в кастрюле {{ grams(it.fridge_available_g) }}</span>
    </div>
    <div v-if="it.origin === 'auto'" class="draft">
      <div class="grow small">Предложено планировщиком<template v-if="it.auto_reason">: <i>{{ it.auto_reason }}</i></template>.
        <div class="tiny muted">Поправите порции или перенесёте — станет обычным блюдом.</div></div>
      <button class="text small" :disabled="busy" @click="pin">{{ it.pinned ? "📌 Открепить" : "📌 Закрепить" }}</button>
      <button v-if="canSwap(it)" class="text small" :disabled="busy" @click="swap">🔄 Другое</button>
      <button class="fill small" :disabled="busy" @click="accept">✓ Принять</button>
    </div>

    <div class="portions">
      <div v-for="p in it.portions" :key="p.id" class="portion" :class="{ eaten: p.is_eaten }">
        <div class="who"><b v-if="p.member_id">{{ p.member_name }}</b><span v-else class="muted">Гость</span>
          <div class="tiny muted">{{ fmt(p.calories) }} ккал · {{ p.is_eaten ? "✓ съел" + (p.eaten_from_pot_id ? " · из холодильника" : "") : "в плане" }}</div></div>
        <label class="w"><input v-model.number="weights[p.id]" type="number" min="1" max="2000" step="any" inputmode="decimal"
               :aria-label="'Порция, г: ' + (p.member_name || 'гость')" @keydown.enter="p.is_eaten ? saveWeight(p) : eat(p)"><span class="muted">г</span></label>
        <div class="acts">
          <button v-if="changed(p)" class="small" :disabled="busy" @click="saveWeight(p)">Сохранить</button>
          <button v-if="!p.is_eaten" class="fill small" :disabled="busy" title="Съедено (вес — из поля)" @click="eat(p)">Съел</button>
          <button v-else class="text small" :disabled="busy" title="Отменить «съедено»" @click="uneat(p)">↺</button>
          <button v-if="p.is_eaten && p.eaten_from_pot_id" class="text small" :disabled="busy"
                  title="Ели не из этой кастрюли — вес в неё не вернётся" @click="detach(p)">без холодильника</button>
          <button class="text small" :disabled="busy" :aria-label="'Убрать порцию: ' + (p.member_name || 'гость')" @click="removePortion(p)">✕</button>
        </div>
      </div>
    </div>

    <div class="row">
      <select v-model="addWho" class="who-sel" aria-label="Добавить едока">
        <option value="">+ Добавить едока…</option>
        <option v-for="m in missing" :key="m.id" :value="String(m.id)">{{ m.name }}</option>
        <option value="guest">Гость</option>
      </select>
      <template v-if="addWho">
        <input v-model.number="addWeight" type="number" min="1" max="2000" step="any" class="num-in" aria-label="Вес порции, г"><span class="small muted">г</span>
        <button class="small" :disabled="busy" @click="addPortion">Добавить</button>
      </template>
    </div>

    <details>
      <summary class="small">Перенести на другой день или приём пищи</summary>
      <div class="row move">
        <input v-model="moveDate" type="date" aria-label="День">
        <select v-model="moveMeal" aria-label="Приём пищи"><option v-for="m in MEALS" :key="m.key" :value="m.key">{{ m.label }}</option></select>
        <button class="small" :disabled="busy" @click="move">Перенести</button>
      </div>
    </details>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text danger" :disabled="busy" @click="removeItem">Удалить блюдо</button>
      <span class="grow"></span>
      <button v-if="uneaten" class="fill" :disabled="busy" @click="eatAll">✓ Все поели</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.badge { font-size: 12px; padding: 3px 10px; border-radius: 999px; background: var(--enamel-2); color: var(--muted); }
.badge.ok { background: var(--rim-soft); color: var(--rim); }
.badge.warn { background: var(--beak-soft); color: var(--cook); }
.badge.info { color: var(--sky); }
.draft { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 10px 12px; border-radius: var(--r-in);
  border: 1px dashed var(--graphite); background: var(--graphite-soft); }
.grow { flex: 1; min-width: 180px; }
.portions { display: flex; flex-direction: column; }
.portion { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 0; border-top: 1px solid var(--line); }
.portion:first-child { border-top: 0; }
.portion.eaten .who b { color: var(--rim); }
.who { flex: 1; min-width: 120px; }
.w { display: flex; align-items: center; gap: 6px; }
.w input, .num-in { width: 92px; }
.acts { display: flex; align-items: center; gap: 4px; }
.small { font-size: 14px; }
button.small { min-height: 40px; padding: 0 12px; }
.who-sel { max-width: 220px; }
summary { cursor: pointer; color: var(--muted); }
.move { margin-top: 8px; }
.move input { width: 170px; }
.move select { width: 150px; }
.err { color: var(--tomato); margin: 0; }
.danger { color: var(--tomato); }
</style>
