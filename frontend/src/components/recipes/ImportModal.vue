<script setup lang="ts">
// Импорт рецептов из YAML (docs/RECIPE_IMPORT.md): файл → отчёт без записи → выбор продуктов для несопоставленных
// ингредиентов и «обновить» для уже существующих рецептов → «Импортировать». Каждое изменение выбора — снова отчёт
// без записи (сервер сам сопоставляет и считает). Новый продукт заводится тут же обычным поиском (OFF / вручную).
import { computed, reactive, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { ensureCatalog, loadRecipes, variantIndex } from "../../catalog";
import { activeVariantOf, draftError, saveDraft, type Draft } from "../../drafts";
import { toast, toastError } from "../../session";
import { fmt, plural } from "../../util";
import OffDraftCard from "../finder/OffDraftCard.vue";
import ProductFinder from "../finder/ProductFinder.vue";
import ModalSheet from "../ModalSheet.vue";

type Report = Schemas["RecipeImportReport"];
type Ing = Schemas["ImportIngredient"];
type Cand = Schemas["ImportCandidate"];
const emit = defineEmits<{ close: [] }>();

ensureCatalog().catch(toastError);

const content = ref("");
const fileName = ref("");
const pasting = ref(false);
const pasted = ref("");
const report = ref<Report | null>(null);
const done = ref<Report | null>(null);
const busy = ref(false);
const error = ref("");
const choices = reactive<Record<string, number | null>>({});
const update = reactive(new Set<number>());

async function call(dryRun: boolean): Promise<Report | null> {
  busy.value = true;
  error.value = "";
  try {
    return await ok(api.POST("/api/v1/recipes/import", { body: { content: content.value, dry_run: dryRun, choices, update: [...update] } }));
  } catch (e) {
    error.value = (e as Error).message;
    return null;
  } finally { busy.value = false; }
}
async function analyze() { const r = await call(true); if (r) report.value = r; }

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement;
  const f = input.files?.[0];
  input.value = "";
  if (!f) return;
  fileName.value = f.name;
  content.value = await f.text();
  resetChoices();
  await analyze();
}
async function usePasted() {
  if (!pasted.value.trim()) return;
  fileName.value = "вставленный текст";
  content.value = pasted.value;
  pasting.value = false;
  resetChoices();
  await analyze();
}
function resetChoices() {
  for (const k of Object.keys(choices)) delete choices[k];
  update.clear();
  report.value = null;
  editing.value = null;
}

// ---- ингредиенты
const blocking = (i: Ing) => i.status === "ambiguous" || i.status === "missing" || (i.status !== "skipped" && !!i.pick?.kbju_missing);
const ingRank = (i: Ing) => (blocking(i) ? 0 : i.status === "fuzzy" ? 1 : i.status === "matched" ? 3 : 2);
const ings = computed(() => [...(report.value?.ingredients ?? [])].sort((a, b) => ingRank(a) - ingRank(b)));
const attention = computed(() => ings.value.filter((i) => i.status !== "matched" || i.pick?.kbju_missing));
const matched = computed(() => ings.value.filter((i) => i.status === "matched" && !i.pick?.kbju_missing));
const waitingCount = computed(() => ings.value.filter(blocking).length);

const STATUS: Record<string, string> = {
  missing: "не нашли", ambiguous: "несколько похожих", fuzzy: "похожий — проверьте", chosen: "выбран", skipped: "пропущен",
};
const statusOf = (i: Ing) => (i.status !== "skipped" && i.pick?.kbju_missing ? "нет КБЖУ" : STATUS[i.status] ?? "");
const candLabel = (c: Cand) => [c.name, c.brand].filter(Boolean).join(" · ");
const inRecipes = (i: Ing) => { const n = i.recipes?.length ?? 0; return `${n} ${plural(n, "рецепте", "рецептах", "рецептах")}`; };

async function choose(key: string, variantId: number | null) {
  choices[key] = variantId;
  editing.value = null;
  await analyze();
}
async function reset(key: string) { delete choices[key]; editing.value = null; await analyze(); }

// поиск другого продукта (или внести КБЖУ выбранному) — открыт один ингредиент
const editing = ref<string | null>(null);
const finder = reactive<{ variant: number | null; draft: Draft | null; saving: boolean; error: string }>({ variant: null, draft: null, saving: false, error: "" });
function openFinder(i: Ing, kbju = false) {
  editing.value = i.key;
  Object.assign(finder, { variant: kbju && i.pick ? i.pick.variant_id : null, draft: null, saving: false, error: "" });
}
function onPick(key: string, id: number | null) {
  finder.variant = id;
  // продукт без КБЖУ — окно поиска само попросит цифры и после сохранения пришлёт новую версию
  if (id && !variantIndex.value[id]?.kbjuMissing) choose(key, id);
}
async function saveNew(key: string) {
  const d = finder.draft;
  if (!d) return;
  finder.error = draftError(d);
  if (finder.error) return;
  finder.saving = true;
  try {
    const p = await saveDraft(d);
    const id = activeVariantOf(p, d.manufacturer || d.brand);
    if (!id) throw new Error(`У продукта «${p.name}» нет активной версии КБЖУ`);
    await choose(key, id);
  } catch (e) { finder.error = (e as Error).message; } finally { finder.saving = false; }
}

// ---- рецепты
const R_STATUS: Record<string, string> = {
  create: "новый", update: "обновить", exists: "уже есть", waiting: "ждёт выбора", error: "ошибка",
  created: "создан", updated: "обновлён", skipped: "пропущен",
};
const shown = computed(() => (done.value ?? report.value)?.recipes ?? []);
const count = (s: string) => shown.value.filter((r) => r.status === s).length;
const toImport = computed(() => count("create") + count("update"));
async function toggleUpdate(n: number) {
  if (update.has(n)) update.delete(n); else update.add(n);
  await analyze();
}

async function runImport() {
  const r = await call(false);
  if (!r) return;
  done.value = r;
  await loadRecipes();
  const parts = [r.created && `создано ${r.created}`, r.updated && `обновлено ${r.updated}`].filter(Boolean);
  toast(parts.length ? `Рецепты: ${parts.join(", ")}` : "Ничего не импортировано");
}

const SAMPLE = `- name: Сырники
  category: Завтраки
  servings: 4
  cooked_weight: 600
  meal_types: [breakfast]
  ingredients:
    - {product: Творог 5%, amount: 400, unit: г}
    - {product: Яйцо куриное, amount: 1, unit: шт, grams: 55}
    - {product: Соль, to_taste: true}
  steps: |
    1. Смешать…`;
</script>

<template>
  <ModalSheet title="Импорт рецептов" wide @close="emit('close')">
    <!-- 1. файл -->
    <template v-if="!report && !done">
      <p class="small">Загрузите файл <b>.yaml</b> со списком рецептов. Сначала покажем, что получится, — ничего не запишется,
        пока вы не нажмёте «Импортировать».</p>
      <div class="pick">
        <label class="button fill">Выбрать файл<input type="file" accept=".yaml,.yml,text/yaml,text/plain" hidden @change="onFile"></label>
        <button class="text" @click="pasting = !pasting">или вставить текст</button>
      </div>
      <template v-if="pasting">
        <textarea v-model="pasted" rows="10" class="mono" placeholder="- name: …" aria-label="Текст YAML"></textarea>
        <div class="end"><button class="fill" :disabled="busy || !pasted.trim()" @click="usePasted">Проверить</button></div>
      </template>
      <details class="fmt">
        <summary class="small">Как устроен файл</summary>
        <pre class="mono tiny">{{ SAMPLE }}</pre>
        <p class="tiny muted">Единицы — г, мл или шт (для шт и мл — ещё grams, вес в граммах). Ложки и стаканы переведите заранее.
          Необязательно: brand, exact (🎯 именно этот бренд), time, effort (easy/special), keeps_days, freezable, allow_half,
          in_rotation, source, notes. Полное описание — docs/RECIPE_IMPORT.md.</p>
      </details>
    </template>

    <!-- 2. отчёт -->
    <template v-else>
      <div class="file small">
        <span class="muted">Файл: <b>{{ fileName }}</b></span>
        <label v-if="!done" class="button text small">Другой файл<input type="file" accept=".yaml,.yml,text/yaml,text/plain" hidden @change="onFile"></label>
      </div>
      <div class="counts small" aria-live="polite">
        <template v-if="done">
          <span v-if="count('created')" class="pill ok">создано {{ count("created") }}</span>
          <span v-if="count('updated')" class="pill ok">обновлено {{ count("updated") }}</span>
          <span v-if="count('skipped')" class="pill">пропущено {{ count("skipped") }}</span>
        </template>
        <template v-else>
          <span v-if="count('create')" class="pill ok">новых {{ count("create") }}</span>
          <span v-if="count('update')" class="pill ok">обновить {{ count("update") }}</span>
          <span v-if="count('exists')" class="pill">уже есть {{ count("exists") }}</span>
        </template>
        <span v-if="count('waiting')" class="pill wait">ждут выбора {{ count("waiting") }}</span>
        <span v-if="count('error')" class="pill bad">с ошибками {{ count("error") }}</span>
        <span v-if="busy" class="muted">считаю…</span>
      </div>

      <section v-if="!done && attention.length" class="block">
        <h3>Продукты <span v-if="waitingCount" class="muted small">— выберите для {{ waitingCount }}</span></h3>
        <p class="tiny muted">Сами продукты не заводим: выберите похожий из справочника, найдите другой (можно в Open Food Facts или
          ввести вручную) или пропустите ингредиент.</p>
        <div v-for="i in attention" :key="i.key" class="ing" :class="{ need: blocking(i), pencil: i.status === 'fuzzy' }">
          <div class="ih">
            <span class="what"><b>{{ i.product }}</b><span v-if="i.brand" class="muted"> · {{ i.brand }}</span>
              <span class="tiny muted"> · в {{ inRecipes(i) }}</span></span>
            <span class="st tiny">{{ statusOf(i) }}</span>
          </div>
          <div v-if="i.pick && i.status !== 'skipped'" class="cur small">
            → {{ candLabel(i.pick) }} <span class="muted">· {{ i.pick.kbju_missing ? "нет КБЖУ" : fmt(i.pick.calories) + " ккал/100 г" }}</span>
          </div>
          <div v-if="i.candidates?.length && (i.status === 'ambiguous' || i.status === 'fuzzy')" class="cands">
            <button v-for="c in (i.candidates ?? []).filter((c) => c.variant_id !== i.pick?.variant_id)" :key="c.variant_id" class="chip"
                    :disabled="busy" @click="choose(i.key, c.variant_id)">
              {{ candLabel(c) }} <span class="muted">{{ c.kbju_missing ? "нет КБЖУ" : fmt(c.calories) + " ккал" }}</span></button>
          </div>
          <div v-if="editing !== i.key" class="acts">
            <button v-if="i.pick?.kbju_missing && i.status !== 'skipped'" class="small fill" @click="openFinder(i, true)">Внести КБЖУ</button>
            <button class="text small" @click="openFinder(i)">{{ i.status === "missing" ? "Найти или завести" : "Другой продукт" }}</button>
            <button v-if="i.status !== 'skipped'" class="text small" :disabled="busy" @click="choose(i.key, null)">Пропустить</button>
            <button v-if="i.status === 'chosen' || i.status === 'skipped'" class="text small" :disabled="busy" @click="reset(i.key)">Как было</button>
          </div>
          <div v-else class="finder">
            <ProductFinder :model-value="finder.variant" :draft="finder.draft" :initial-query="finder.variant ? '' : i.product" kbju-prompt autofocus
                           @update:model-value="onPick(i.key, $event)" @update:draft="finder.draft = $event" />
            <template v-if="finder.draft">
              <OffDraftCard v-model="finder.draft" />
              <p v-if="finder.error" class="small err" role="alert">{{ finder.error }}</p>
            </template>
            <div class="acts end">
              <button class="text small" @click="editing = null">Отмена</button>
              <button v-if="finder.draft" class="fill small" :disabled="finder.saving" @click="saveNew(i.key)">
                {{ finder.saving ? "Сохраняю…" : "Сохранить продукт" }}</button>
            </div>
          </div>
        </div>
      </section>

      <details v-if="!done && matched.length" class="block">
        <summary class="small">Нашлись в справочнике: {{ matched.length }}</summary>
        <div v-for="i in matched" :key="i.key" class="mrow small">
          <span class="grow">{{ i.product }}<span v-if="i.brand" class="muted"> · {{ i.brand }}</span>
            <span class="muted"> → {{ candLabel(i.pick!) }}, {{ fmt(i.pick!.calories) }} ккал</span></span>
          <button class="text small" @click="openFinder(i)">Другой</button>
          <div v-if="editing === i.key" class="finder full">
            <ProductFinder :model-value="finder.variant" :draft="finder.draft" :initial-query="i.product" kbju-prompt autofocus
                           @update:model-value="onPick(i.key, $event)" @update:draft="finder.draft = $event" />
            <OffDraftCard v-if="finder.draft" v-model="finder.draft" />
            <p v-if="finder.error" class="small err" role="alert">{{ finder.error }}</p>
            <div class="acts end">
              <button class="text small" @click="editing = null">Отмена</button>
              <button v-if="finder.draft" class="fill small" :disabled="finder.saving" @click="saveNew(i.key)">Сохранить продукт</button>
            </div>
          </div>
        </div>
      </details>

      <section class="block">
        <h3>Рецепты</h3>
        <div v-for="r in shown" :key="r.number" class="rec" :class="r.status">
          <div class="rh">
            <span class="num tiny muted">№{{ r.number }}</span>
            <b class="grow">{{ r.name }}</b>
            <span class="st tiny">{{ R_STATUS[r.status] }}</span>
          </div>
          <span v-if="r.status !== 'error' || r.ingredients" class="tiny muted">
            {{ r.category }}<template v-if="r.new_category"> (новая категория)</template><template v-if="r.servings"> · {{ r.servings }} порц.</template><template v-if="r.ingredients"> · {{ r.ingredients }} ингр.</template><template v-if="r.cooked_weight"> · выход {{ fmt(r.cooked_weight) }} г</template><template v-if="r.calories_per_100g != null"> · {{ fmt(r.calories_per_100g) }} ккал/100 г</template>
          </span>
          <ul v-if="r.errors?.length" class="msgs err small"><li v-for="(m, k) in r.errors" :key="k">{{ m }}</li></ul>
          <ul v-if="r.warnings?.length" class="msgs tiny muted"><li v-for="(m, k) in r.warnings" :key="k">{{ m }}</li></ul>
          <label v-if="!done && (r.status === 'exists' || r.status === 'update')" class="upd small">
            <input type="checkbox" :checked="update.has(r.number)" :disabled="busy" @change="toggleUpdate(r.number)">
            Обновить существующий рецепт (состав, порции и шаги — из файла)</label>
        </div>
      </section>
    </template>

    <p v-if="error" class="small err" role="alert">{{ error }}</p>

    <template #foot>
      <template v-if="done">
        <button class="fill" @click="emit('close')">Готово</button>
      </template>
      <template v-else>
        <button class="text" @click="emit('close')">Отмена</button>
        <button v-if="report" class="fill" :disabled="busy || !toImport" @click="runImport">
          {{ toImport ? `Импортировать ${toImport} ${plural(toImport, "рецепт", "рецепта", "рецептов")}` : "Нечего импортировать" }}</button>
      </template>
    </template>
  </ModalSheet>
</template>

<style scoped>
p { margin: 0; }
h3 { font-size: 16px; }
.pick { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
label.button { display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 0 18px; border-radius: 999px;
  border: 2px solid var(--rim); font-weight: 600; cursor: pointer; }
label.button.fill { background: var(--rim); color: var(--on-fill); }
label.button.text { border-color: transparent; color: var(--rim); min-height: 36px; padding: 0 10px; }
.mono { font-family: ui-monospace, Menlo, monospace; }
textarea.mono { font-size: 13px; }
.fmt pre { margin: 8px 0; padding: 10px 12px; border-radius: var(--r-in); background: var(--enamel-2); overflow-x: auto; white-space: pre; }
.fmt summary, details.block > summary { cursor: pointer; color: var(--rim); font-weight: 600; min-height: 32px; }
.end { display: flex; justify-content: flex-end; }
.file { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.counts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.pill { padding: 2px 10px; border-radius: 999px; background: var(--enamel-2); border: 1px solid var(--line); }
.pill.ok { background: var(--rim-soft); color: var(--rim); border-color: transparent; }
.pill.wait { background: var(--beak-soft); border-color: transparent; }
.pill.bad { color: var(--tomato); border-color: var(--tomato); }
.block { display: flex; flex-direction: column; gap: 8px; }
.ing { display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: var(--r-in); border: 1.5px solid var(--line); background: var(--enamel); }
.ing.need { border-color: var(--beak); background: var(--beak-soft); }
/* подставлено приложением — «карандашом» */
.ing.pencil { border: 1.5px dashed var(--graphite); background: var(--graphite-soft); }
.ih, .rh { display: flex; align-items: baseline; gap: 8px; }
.what { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.st { flex: none; padding: 1px 8px; border-radius: 999px; border: 1px solid currentColor; color: var(--muted); white-space: nowrap; }
.cur { overflow-wrap: anywhere; }
.cands { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { min-height: 36px; padding: 0 12px; font-size: 13px; font-weight: 500; border-color: var(--line); background: var(--enamel); color: var(--ink); text-align: left; }
.chip:hover { border-color: var(--rim); }
.acts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.acts.end { justify-content: flex-end; }
.finder { display: flex; flex-direction: column; gap: 8px; }
.finder.full { flex-basis: 100%; }
.mrow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 4px 0; border-top: 1px solid var(--line); }
.grow { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.rec { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px; border-radius: var(--r-in); border: 1.5px solid var(--line); }
.rec.create .st, .rec.update .st, .rec.created .st, .rec.updated .st { color: var(--rim); }
.rec.waiting { border-color: var(--beak); }
.rec.error { border-color: var(--tomato); }
.rec.error .st { color: var(--tomato); }
.rec.exists, .rec.skipped { opacity: 0.85; }
.num { flex: none; }
.msgs { margin: 0; padding-left: 18px; }
.err { color: var(--tomato); }
.upd { display: flex; align-items: center; gap: 10px; min-height: 44px; cursor: pointer; }
.upd input { width: 20px; height: 20px; min-height: 0; flex: none; accent-color: var(--rim); }
button.small { min-height: 40px; padding: 0 12px; font-size: 14px; }
</style>
