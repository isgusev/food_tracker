<script setup lang="ts">
// Шаблоны недель: сохранить текущую неделю и применить сохранённую (добавляет к плану, не заменяет).
import { onMounted, ref } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { toast, toastError } from "../../session";
import { dayMonthShort } from "../../util";
import ModalSheet from "../ModalSheet.vue";

const props = defineProps<{ weekStart: string }>();
const emit = defineEmits<{ close: []; applied: [] }>();

const list = ref<Schemas["TemplateResponse"][]>([]);
const name = ref("");
const busy = ref(false);
const DAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
const load = async () => { try { list.value = await ok(api.GET("/api/v1/plan/templates")); } catch (e) { toastError(e); } };
onMounted(load);

async function save() {
  if (!name.value.trim()) return;
  busy.value = true;
  try {
    await ok(api.POST("/api/v1/plan/templates", { body: { name: name.value.trim(), week_start: props.weekStart } }));
    name.value = "";
    toast("Неделя сохранена как шаблон");
    await load();
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
async function apply(t: Schemas["TemplateResponse"]) {
  busy.value = true;
  try {
    const r = await ok(api.POST("/api/v1/plan/templates/{template_id}/apply", { params: { path: { template_id: t.id } }, body: { week_start: props.weekStart } }));
    toast(`Добавлено блюд: ${r.created}` + (r.skipped ? `, пропущено ${r.skipped} (рецепт удалён или едок скрыт)` : ""));
    emit("applied");
  } catch (e) { toastError(e); } finally { busy.value = false; }
}
async function remove(t: Schemas["TemplateResponse"]) {
  if (!confirm(`Удалить шаблон «${t.name}»?`)) return;
  try { await ok(api.DELETE("/api/v1/plan/templates/{template_id}", { params: { path: { template_id: t.id } } })); await load(); }
  catch (e) { toastError(e); }
}
const perDay = (t: Schemas["TemplateResponse"]) =>
  DAYS.map((d, i) => `${d} ${(t.meals_per_day as Record<string, number>)[String(i)] || 0}`).join(", ");
</script>

<template>
  <ModalSheet title="Шаблоны недель" @close="emit('close')">
    <div class="save">
      <input v-model="name" placeholder="Например, «Обычная неделя»" aria-label="Название шаблона" @keydown.enter="save">
      <button class="fill" :disabled="busy || !name.trim()" @click="save">Сохранить эту неделю</button>
    </div>
    <p class="small muted">Сохраняются блюда и порции каждого. Применение добавляет блюда к неделе с {{ dayMonthShort(weekStart) }} — уже запланированное остаётся.</p>
    <p v-if="!list.length" class="muted">Шаблонов пока нет.</p>
    <div v-else class="list">
      <div v-for="t in list" :key="t.id" class="t">
        <div class="grow"><b>{{ t.name }}</b><div class="tiny muted">{{ t.items_count }} блюд · {{ perDay(t) }}</div></div>
        <button class="fill small" :disabled="busy" @click="apply(t)">Применить</button>
        <button class="text small" :aria-label="'Удалить шаблон ' + t.name" @click="remove(t)">✕</button>
      </div>
    </div>
  </ModalSheet>
</template>

<style scoped>
.save { display: flex; flex-wrap: wrap; gap: 8px; }
.save input { flex: 1; min-width: 200px; }
p { margin: 0; }
.list { display: flex; flex-direction: column; }
.t { display: flex; align-items: center; gap: 8px; padding: 10px 0; border-top: 1px solid var(--line); }
.t:first-child { border-top: 0; }
.grow { flex: 1; min-width: 0; }
button.small { min-height: 40px; padding: 0 12px; font-size: 14px; }
</style>
