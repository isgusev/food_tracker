<script setup lang="ts">
// «+ Продукт»: тот же поиск (справочник → штрихкод/📷 → Open Food Facts → вручную). Выбрали уже существующий —
// открываем его карточку; черновик сохраняется в справочник без «переиспользования» (дубль — ошибка сервера).
import { ref, watch } from "vue";
import type { Schemas } from "../../api/client";
import { variantIndex } from "../../catalog";
import { draftError, saveDraft, type Draft } from "../../drafts";
import { toast } from "../../session";
import ModalSheet from "../ModalSheet.vue";
import OffDraftCard from "../finder/OffDraftCard.vue";
import ProductFinder from "../finder/ProductFinder.vue";

const emit = defineEmits<{ close: []; saved: []; open: [p: Schemas["ProductResponse"]] }>();
const variantId = ref<number | null>(null);
const draft = ref<Draft | null>(null);
const busy = ref(false);
const error = ref("");
watch(variantId, (id) => { const v = id ? variantIndex.value[id] : undefined; if (v) emit("open", v.product); });

async function save() {
  error.value = "";
  if (!draft.value) { error.value = "Найдите продукт или введите его вручную"; return; }
  if ((error.value = draftError(draft.value))) return;
  busy.value = true;
  try {
    const p = await saveDraft(draft.value, { reuse: false });
    toast(`«${p.name}» добавлен`);
    emit("saved");
  } catch (e) { error.value = (e as Error).message; } finally { busy.value = false; }
}
</script>

<template>
  <ModalSheet title="Новый продукт" @close="emit('close')">
    <div class="field"><span class="lbl">Что за продукт</span>
      <ProductFinder v-model="variantId" v-model:draft="draft" autofocus />
      <span v-if="!draft" class="tiny muted">Сначала ищем в справочнике (найденный откроется), затем в Open Food Facts; нет нигде — «Ввести вручную».</span>
    </div>
    <OffDraftCard v-if="draft" v-model="draft" />
    <p v-if="error" class="err" role="alert">{{ error }}</p>
    <template #foot>
      <button class="text" @click="emit('close')">Отмена</button>
      <button class="fill" :disabled="busy || !draft" @click="save">Сохранить в справочник</button>
    </template>
  </ModalSheet>
</template>

<style scoped>
.field { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 14px; font-weight: 600; }
.err { color: var(--tomato); margin: 0; }
</style>
