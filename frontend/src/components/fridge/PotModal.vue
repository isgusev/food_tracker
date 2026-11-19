<script setup lang="ts">
// Кастрюля: сколько вышло и сколько осталось, фактический состав, срок заготовки — всё одной кнопкой «Сохранить»;
// морозилка, «выбросить» (в архив) и удаление (смотрим, где она уже учтена). Успешное действие закрывает окно.
import { computed, ref, watch } from "vue";
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
const origTotal = num(props.pot.total_cooked_weight);
const origRemaining = num(props.pot.current_remaining_weight);
const eaten = origTotal - origRemaining;            // уже съедено из кастрюли — не меняется
const total = ref<number | string>(origTotal);
const remaining = ref<number | string>(origRemaining);
const remainingTouched = ref(false);
// поменяли «вышло готового» — «осталось» сдвигается на ту же разницу (если остаток не правили руками)
watch(total, (t) => { if (!remainingTouched.value) remaining.value = Math.max(0, Math.round((num(t) - eaten) * 10) / 10); });
const origIngredients = (props.pot.actual_ingredients ?? []).map((i) => ({ variant_id: i.variant_id, weight_g: num(i.weight_g) }));
const ingredients = ref<IngredientRow[]>(origIngredients.map((i) => ({ ...i })));
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

const sig = (rows: { variant_id: number | null; weight_g: unknown; draft?: unknown }[]) =>
  JSON.stringify(rows.map((r) => [r.variant_id, num(r.weight_g), !!r.draft]));
const compChanged = computed(() => sig(ingredients.value) !== sig(origIngredients));
const totalChanged = computed(() => num(total.value) !== origTotal);
const remainingChanged = computed(() => num(remaining.value) !== origRemaining);
const keepsChanged = computed(() => props.pot.is_frozen && !!keepsUntil.value && keepsUntil.value !== props.pot.keeps_until);
const dirty = computed(() => compChanged.value || totalChanged.value || remainingChanged.value || keepsChanged.value);

/** Что станет с планами по новому остатку (допуск семьи). */
function remainderNote(r: number): string {
  const planned = num(props.pot.planned_g);
  if (r >= planned) return "";
  const tol = (session.household?.portion_tolerance ?? 15) / 100;
  return r >= planned * (1 - tol) ? " Порции в плане уменьшены пропорционально." : " Планам, которым не хватит, — снова «надо приготовить».";
}

/** Одна кнопка: состав и выход (если меняли) → остаток (если задан руками иначе, чем сдвиг) → срок заготовки. */
async function save() {
  if (num(total.value) < eaten) { error.value = `Из кастрюли уже съели ${grams(eaten)} — готового не может быть меньше`; return; }
  if (num(remaining.value) > num(total.value)) { error.value = "Осталось больше, чем вышло готового — поправьте «Вышло готового»"; return; }
  await run(async () => {
    let remainingNow = origRemaining;
    if (compChanged.value || totalChanged.value) {
      await resolveDraftIngredients(ingredients.value);   // новые продукты — сначала в справочник
      const r = await ok(api.PUT("/api/v1/recipes/cooking-logs/{log_id}/ingredients", { ...path(), body: {
        ingredients: ingredients.value.filter((i) => i.variant_id && num(i.weight_g) > 0)
          .map((i) => ({ variant_id: i.variant_id!, weight_g: num(i.weight_g), exact: false })),
        total_cooked_weight: totalChanged.value ? num(total.value) : null,
      } }));
      remainingNow = num(r.current_remaining_weight);
    }
    if (num(remaining.value) !== remainingNow) {
      await ok(api.PATCH("/api/v1/recipes/cooking-logs/{log_id}", { ...path(), body: { current_remaining_weight: num(remaining.value) } }));
    }
    if (keepsChanged.value) {
      await ok(api.POST("/api/v1/recipes/cooking-logs/{log_id}/freeze", { ...path(), body: { keeps_until: keepsUntil.value } }));
    }
  }, "Сохранено." + remainderNote(num(remaining.value)));
}
const freeze = () => run(() => ok(api.POST("/api/v1/recipes/cooking-logs/{log_id}/freeze", { ...path(), body: {} })), "Остаток в морозилке");
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

    <div class="line">
      <label class="field"><span class="lbl">Вышло готового, г</span>
        <input v-model="total" type="number" min="1" step="any" inputmode="decimal"></label>
      <label class="field"><span class="lbl">Осталось сейчас, г</span>
        <input v-model="remaining" type="number" min="0" :max="num(total)" step="any" inputmode="decimal" @input="remainingTouched = true"></label>
      <label v-if="pot.is_frozen" class="field"><span class="lbl">❄️ Годна до</span><input v-model="keepsUntil" type="date" :min="todayIso"></label>
    </div>
    <p class="small muted">
      Запланировано {{ grams(pot.planned_g) }}<template v-if="eaten > 0"> · уже съели {{ grams(eaten) }}</template>.
      Положили больше или меньше — поправьте состав и «вышло готового»: остаток сдвинется на ту же разницу.
    </p>

    <div>
      <button v-if="!editIngr" class="text" @click="editIngr = true">Изменить фактический состав…</button>
      <div v-else class="ingr">
        <h3>Фактический состав</h3>
        <IngredientsEditor v-model="ingredients" :cooked-weight="total" />
      </div>
    </div>

    <div v-if="usage" class="note">
      <template v-if="usage.past_dates?.length">
        Удалить нельзя: блюдо уже учтено в дневнике за {{ (usage.past_dates ?? []).map(dayMonth).join(", ") }}. Если остаток испортился — «Выбросить остаток».
      </template>
      <template v-else-if="usage.current_future_dates?.length">
        <p>Блюдо в плане на {{ (usage.current_future_dates ?? []).map(dayMonth).join(", ") }}. Что сделать с этими записями?</p>
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
      <button v-if="!pot.is_frozen" class="text" :disabled="busy" @click="freeze">❄️ Заморозить</button>
      <button v-else class="text" :disabled="busy" @click="unfreeze">Достать из морозилки</button>
      <button class="text" :disabled="busy" @click="discard">Выбросить остаток</button>
      <button class="fill" :disabled="busy || !dirty" @click="save">{{ busy ? "Сохраняю…" : "Сохранить" }}</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
.late { color: var(--tomato); }
.line { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 6px; width: 200px; }
@media (max-width: 600px) { .field { width: calc(50% - 5px); } }
.lbl { font-size: 14px; font-weight: 600; }
.ingr { display: flex; flex-direction: column; gap: 10px; }
h3 { font-size: 16px; }
.note { padding: 12px; border-radius: var(--r-in); background: var(--beak-soft); display: flex; flex-direction: column; gap: 10px; }
.err { color: var(--tomato); }
.danger { color: var(--tomato); border-color: var(--tomato); }
.text.danger { border-color: transparent; }
.grow { flex: 1; }
</style>
