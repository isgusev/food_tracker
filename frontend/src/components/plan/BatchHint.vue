<script setup lang="ts">
// Подсказка в форме плана: что останется от закладки рецепта после готовки (GET /plan/batch-check).
// Считает вместе с другими неприготовленными блюдами этого рецепта, пока закладка свежая, — как список покупок.
// «Разделить всю закладку» — emit fit(target): форма пропорционально подгоняет порции под target граммов.
import { ref, watch } from "vue";
import { api, ok, type Schemas } from "../../api/client";
import { fmt, grams, num } from "../../util";

const props = defineProps<{ recipeId: number | null; date: string; weight: number; itemId?: number; disabled?: boolean }>();
const emit = defineEmits<{ fit: [target: number] }>();

const check = ref<Schemas["BatchCheck"] | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;

watch(() => [props.recipeId, props.date, props.weight, props.itemId], () => {
  clearTimeout(timer);
  if (!props.recipeId || !(props.weight > 0)) { check.value = null; return; }
  const my = ++seq;
  timer = setTimeout(async () => {
    try {
      const r = await ok(api.GET("/api/v1/plan/batch-check", { params: { query: {
        recipe_id: props.recipeId!, date_day: props.date, weight_g: props.weight, ...(props.itemId ? { item_id: props.itemId } : {}),
      } } }));
      if (my === seq) check.value = r;
    } catch { if (my === seq) check.value = null; /* подсказка необязательна */ }
  }, 300);
}, { immediate: true });

/** «готовим 1 закладку / 1,5 закладки / 5 закладок» */
const batchesText = (b: unknown) => {
  const n = num(b);
  const word = n === 1 ? "закладку" : n % 1 || n < 5 ? "закладки" : "закладок";
  return `${fmt(n, n % 1 ? 1 : 0)} ${word}`;
};
</script>

<template>
  <div v-if="check && (check.status === 'leftover' || check.status === 'short')" class="hint" role="status">
    <div class="grow">
      <template v-if="check.status === 'leftover'">
        Готовим {{ batchesText(check.batches) }} — {{ grams(num(check.batches) * num(check.cooked)) }}.
        После еды останется <b>{{ grams(check.leftover) }}</b> — меньше порции ({{ grams(check.portion) }}).
      </template>
      <template v-else>
        Выйдет {{ grams(num(check.batches) * num(check.cooked)) }}, в плане на {{ grams(-num(check.leftover)) }} больше —
        в пределах допуска: при готовке порции немного уменьшатся.
      </template>
      <div v-if="num(check.others) > 0" class="tiny muted">С учётом этого же блюда в соседние дни ({{ grams(check.others) }}).</div>
    </div>
    <button class="small" :disabled="disabled" @click="emit('fit', num(check.target))">
      {{ check.status === "leftover" ? "Разделить всю закладку" : "Подогнать под закладку" }}</button>
  </div>
</template>

<style scoped>
.hint { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 10px 12px; border-radius: var(--r-in);
  background: var(--beak-soft); font-size: 14px; }
.grow { flex: 1; min-width: 200px; }
button.small { min-height: 40px; padding: 0 12px; font-size: 14px; }
</style>
