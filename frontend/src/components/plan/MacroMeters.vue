<script setup lang="ts">
// Четыре полосы «план + съеденное против цели»; > 110 % — томатная.
import type { Macros } from "../../plan";
import { fmt } from "../../util";

const props = defineProps<{ value: Macros; target: Macros }>();
const ROWS = [
  { k: "calories", label: "Ккал", unit: "" },
  { k: "proteins", label: "Белки", unit: " г" },
  { k: "fats", label: "Жиры", unit: " г" },
  { k: "carbs", label: "Углеводы", unit: " г" },
] as const;
const pct = (k: keyof Macros) => Math.min(100, (props.value[k] / (props.target[k] || 1)) * 100);
const over = (k: keyof Macros) => props.value[k] > props.target[k] * 1.1;
</script>

<template>
  <div class="meters">
    <div v-for="r in ROWS" :key="r.k" class="m">
      <div class="lbl small"><span>{{ r.label }}</span><span><b>{{ fmt(value[r.k]) }}</b> / {{ fmt(target[r.k]) }}{{ r.unit }}</span></div>
      <div class="bar"><i :class="{ over: over(r.k) }" :style="{ width: pct(r.k) + '%' }"></i></div>
    </div>
  </div>
</template>

<style scoped>
.meters { display: flex; flex-direction: column; gap: 10px; }
.lbl { display: flex; justify-content: space-between; margin-bottom: 4px; }
.bar { height: 8px; border-radius: 999px; background: var(--enamel-2); overflow: hidden; border: 1px solid var(--line); }
.bar i { display: block; height: 100%; background: var(--rim); border-radius: 999px; }
.bar i.over { background: var(--tomato); }
</style>
