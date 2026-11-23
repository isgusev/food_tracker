<script setup lang="ts">
// КБЖУ на 100 г с мягкой проверкой Атуотера — то же правило, что на сервере (app/domain.py):
// предупреждение, если расхождение с 4Б + 9Ж + 4У больше 10 ккал И больше 15 %.
import { computed } from "vue";
import type { Kbju } from "../../drafts";
import { fmt, num } from "../../util";

const model = defineModel<Kbju>({ required: true });
const check = computed(() => {
  const k = model.value;
  const calc = 4 * num(k.proteins) + 9 * num(k.fats) + 4 * num(k.carbs);
  const diff = Math.abs(num(k.calories) - calc);
  return { calc, off: num(k.calories) > 0 && diff > 10 && diff > 0.15 * calc };
});
const FIELDS = [
  { k: "calories", label: "Ккал / 100 г" },
  { k: "proteins", label: "Белки, г" },
  { k: "fats", label: "Жиры, г" },
  { k: "carbs", label: "Углеводы, г" },
] as const;
</script>

<template>
  <div class="kbju">
    <div class="grid">
      <label v-for="f in FIELDS" :key="f.k"><span>{{ f.label }}</span>
        <input v-model="model[f.k]" type="number" min="0" step="any" inputmode="decimal"></label>
    </div>
    <p v-if="check.off" class="warn tiny" role="status">
      По БЖУ выходит ≈ {{ fmt(check.calc) }} ккал — проверьте цифры с упаковки (сохранить можно, версия будет помечена).
    </p>
  </div>
</template>

<style scoped>
.kbju { display: flex; flex-direction: column; gap: 6px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
label { display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--muted); }
.warn { color: var(--cook); margin: 0; }
@media (max-width: 520px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
