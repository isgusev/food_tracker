<script setup lang="ts">
// Кастрюля: остаток (с подсказкой, что станет с планами при допуске семьи), фактический состав, морозилка,
// «выбросить» (в архив) и удаление (смотрим, где она уже учтена). Успешное действие закрывает окно.
import { ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { resolveDraftIngredients, type IngredientRow } from "../../drafts";
import { session, toast } from "../../session";
import { dayMonth, fmt, fmtMacro, grams, num, today } from "../../util";
import IngredientsEditor from "../finder/IngredientsEditor.vue";
import ModalSheet from "../ModalSheet.vue";

type Pot = Schemas["RecipeCookingLogResponse"];
const props = defineProps<{ pot: Pot; name: string }>();
const emit = defineEmits<{ close: []; saved: [] }>();

const todayIso = today();
const remaining = ref<number | string>(num(props.pot.current_remaining_weight));
const ingredients = ref<IngredientRow[]>((props.pot.actual_ingredients ?? []).map((i) => ({ variant_id: i.variant_id, weight_g: num(i.weight_g) })));
const editIngr = ref(false);
const keepsUntil = ref(props.pot.keeps_until || "");
const usage = ref<Schemas["PotUsageResponse"] | null>(null);
const busy = ref(false);
const error = ref("");
const path = () => ({ params: { path: { log_id: props.pot.id } } });

async function run(fn: () => Promise<unknown>, msg: string) {
  error.value = "";
  busy.value = true;
  try { await fn(); toast(msg); emit("saved"); }
  catch (e) { error.value = (e as Error).message; }
  finally { busy.value = false; }
}

function remainderMessage(): string {
  const r = num(remaining.value), planned = num(props.pot.planned_g);
  if (r >= planned) return "Остаток обновлён";
  const tol = (session.household?.portion_tolerance ?? 15) / 100;
  return r >= planned * (1 - tol)
    ? "Остаток обновлён. Порции в плане уменьшены пропорционально"
    : "Остаток обновлён. Планам, которым не хватит, — снова «надо приготовить»";
}
const saveRemaining = () => run(() => ok(api.PATCH("/api/v1/recipes/cooking-logs/{log_id}", { ...path(),
  body: { current_remaining_weight: num(remaining.value) } })), remainderMessage());
const saveIngredients = () => run(async () => {
  await resolveDraftIngredients(ingredients.value);   // новые продукты — сначала в справочник
  await ok(api.PUT("/api/v1/recipes/cooking-logs/{log_id}/ingredients", { ...path(), body: {
    ingredients: ingredients.value.filter((i) => i.variant_id && num(i.weight_g) > 0)
      .map((i) => ({ variant_id: i.variant_id!, weight_g: num(i.weight_g), exact: false })),
  } }));
}, "Состав пересчитан");
const freeze = () => run(() => ok(api.POST("/api/v1/recipes/cooking-logs/{log_id}/freeze", { ...path(), body: {} })), "Остаток в морозилке");
const saveKeeps = () => run(() => ok(api.POST("/api/v1/recipes/cooking-logs/{log_id}/freeze", { ...path(), body: { keeps_until: keepsUntil.value || null } })),
  "Срок заготовки сохранён");
const unfreeze = () => run(() => ok(api.POST("/api/v1/recipes/cooking-logs/{log_id}/unfreeze", path())), "Достали из морозилки");
function discard() {
  if (!confirm(`Выбросить остаток (${grams(props.pot.current_remaining_weight)})? Блюдо уйдёт в архив, планы по нему снова станут «надо приготовить».`)) return;
  run(() => ok(api.POST("/api/v1/recipes/cooking-logs/{log_id}/discard", path())), "Списано в архив");
}
async function askDelete() {
  error.value = "";
  try { usage.value = await ok(api.GET("/api/v1/recipes/cooking-logs/{log_id}/usage", path())); }
  catch (e) { error.value = (e as Error).message; }
}
const doDelete = (removeFromDiary: boolean) => run(async () => {
  const r = await api.DELETE("/api/v1/recipes/cooking-logs/{log_id}", { params: { path: { log_id: props.pot.id }, query: { remove_from_diary: removeFromDiary } } });
  if (!r.response.ok) await ok(Promise.resolve(r));
}, "Удалено из холодильника");
const cookedAt = new Date(props.pot.cooked_at ?? "").toLocaleString("ru-RU", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit" });
</script>

<template>
  <ModalSheet :title="name" wide @close="emit('close')">
    <p class="small muted">
      Приготовлено {{ cookedAt }} · сырой вес {{ grams(pot.total_raw_weight) }} → готовый {{ grams(pot.total_cooked_weight) }}
      <template v-if="pot.good_until && !pot.is_frozen"> · <span :class="{ late: pot.good_until < todayIso }">съесть до {{ dayMonth(pot.good_until) }}</span></template>
    </p>
    <p class="small"><span class="muted">На 100 г: </span><b>{{ fmt(pot.calories_per_100g) }} ккал</b> · Б {{ fmtMacro(pot.proteins_per_100g) }} · Ж {{ fmtMacro(pot.fats_per_100g) }} · У {{ fmtMacro(pot.carbs_per_100g) }}</p>

    <div v-if="pot.is_frozen" class="line">
      <label class="field"><span class="lbl">❄️ Заготовка, годна до</span><input v-model="keepsUntil" type="date" :min="todayIso"></label>
      <button :disabled="busy || !keepsUntil || keepsUntil === pot.keeps_until" @click="saveKeeps">Сохранить срок</button>
    </div>

    <div class="line">
      <label class="field"><span class="lbl">Осталось в кастрюле, г</span>
        <input v-model="remaining" type="number" min="0" :max="num(pot.total_cooked_weight)" step="any" inputmode="decimal"></label>
      <button :disabled="busy" @click="saveRemaining">Сохранить остаток</button>
      <span class="small muted">Запланировано: {{ grams(pot.planned_g) }}</span>
    </div>

    <div>
      <button v-if="!editIngr" class="text" @click="editIngr = true">Изменить фактический состав…</button>
      <div v-else class="ingr">
        <h3>Фактический состав</h3>
        <IngredientsEditor v-model="ingredients" :cooked-weight="pot.total_cooked_weight" />
        <div><button class="fill" :disabled="busy" @click="saveIngredients">Пересчитать КБЖУ</button></div>
      </div>
    </div>

    <div v-if="usage" class="note">
      <template v-if="usage.past_dates?.length">
        Удалить нельзя: блюдо уже учтено в дневнике за {{ (usage.past_dates ?? []).join(", ") }}. Если остаток испортился — «Выбросить остаток».
      </template>
      <template v-else-if="usage.current_future_dates?.length">
        <p>Блюдо в плане на {{ (usage.current_future_dates ?? []).join(", ") }}. Что сделать с этими записями?</p>
        <div class="line">
          <button :disabled="busy" @click="doDelete(false)">Оставить в плане (надо приготовить заново)</button>
          <button class="danger" :disabled="busy" @click="doDelete(true)">Удалить и их</button>
        </div>
      </template>
      <template v-else>
        <p>Блюдо нигде не используется. Удалить без следа (например, добавлено по ошибке)?</p>
        <button class="danger" :disabled="busy" @click="doDelete(false)">Удалить</button>
      </template>
    </div>

    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text danger" :disabled="busy" @click="askDelete">Удалить…</button>
      <span class="grow"></span>
      <button v-if="!pot.is_frozen" :disabled="busy" @click="freeze">❄️ Заморозить остаток</button>
      <button v-else :disabled="busy" @click="unfreeze">Достать из морозилки</button>
      <button :disabled="busy" @click="discard">Выбросить остаток</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
.late { color: var(--tomato); }
.line { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 6px; width: 220px; }
.lbl { font-size: 14px; font-weight: 600; }
.ingr { display: flex; flex-direction: column; gap: 10px; }
h3 { font-size: 16px; }
.note { padding: 12px; border-radius: var(--r-in); background: var(--beak-soft); display: flex; flex-direction: column; gap: 10px; }
.err { color: var(--tomato); }
.danger { color: var(--tomato); border-color: var(--tomato); }
.text.danger { border-color: transparent; }
.grow { flex: 1; }
</style>
