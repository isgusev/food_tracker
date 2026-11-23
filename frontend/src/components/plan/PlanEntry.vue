<script setup lang="ts">
// Блюдо в сетке недели: «чернила» — принятое (полоса состояния слева), «карандаш» — предложение автоплана.
import { computed } from "vue";
import { allEaten, canSwap, itemBadge, portionOf, stateClass, type Item } from "../../plan";
import { fmt, grams } from "../../util";

const props = defineProps<{ item: Item; memberId: number | null; memberName: string; busy: boolean; dragging: boolean }>();
const emit = defineEmits<{ open: []; accept: []; pin: []; swap: []; remove: []; dragstart: [e: DragEvent]; dragend: [] }>();

const p = computed(() => portionOf(props.item, props.memberId));
const others = computed(() => props.item.portions.length - (p.value ? 1 : 0));
const badge = computed(() => itemBadge(props.item));
const auto = computed(() => props.item.origin === "auto");
</script>

<template>
  <article class="entry" :class="[stateClass(item), { auto, pinned: item.pinned, fact: allEaten(item), dragging }]"
           draggable="true" tabindex="0" :aria-label="item.name"
           @dragstart="emit('dragstart', $event)" @dragend="emit('dragend')" @click="emit('open')" @keydown.enter.self="emit('open')">
    <div class="name">{{ item.name }}<span v-if="item.pinned" class="pin" title="Закреплено">📌</span></div>
    <div class="meta">
      <template v-if="p">{{ grams(p.weight_g) }} · {{ fmt(p.calories) }} ккал<span v-if="p.is_eaten"> ✓</span></template>
      <template v-else>без {{ memberName }}</template>
      <span v-if="others > 0"> · ещё {{ others }}</span>
    </div>
    <div v-if="!allEaten(item) && badge.cls === 'warn'" class="warn">{{ badge.text }}</div>
    <div v-if="auto && item.auto_reason" class="reason">{{ item.auto_reason }}</div>
    <div v-if="auto" class="acts" @click.stop>
      <button class="da" :disabled="busy" title="Принять — станет обычным блюдом" aria-label="Принять" @click="emit('accept')">✓</button>
      <button class="da" :class="{ on: item.pinned }" :disabled="busy" :aria-label="item.pinned ? 'Открепить' : 'Закрепить'"
              :title="item.pinned ? 'Открепить' : 'Закрепить: новый подбор не заменит'" @click="emit('pin')">📌</button>
      <button v-if="canSwap(item)" class="da" :disabled="busy" title="Другой вариант" aria-label="Другой вариант" @click="emit('swap')">🔄</button>
      <button class="da" :disabled="busy" title="Убрать из плана" aria-label="Убрать" @click="emit('remove')">✕</button>
    </div>
  </article>
</template>

<style scoped>
.entry {
  position: relative; margin-top: 6px; padding: 8px 10px 8px 12px; border-radius: var(--r-in); cursor: pointer;
  background: var(--enamel-2); border: 1px solid transparent;
}
.entry:hover, .entry:focus-visible { border-color: var(--line); }
/* чернила: полоса слева — состояние блюда */
.entry::before { content: ""; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 0 3px 3px 0; background: var(--line); }
.st-to_cook::before { background: var(--cook); }
.st-in_fridge::before { background: var(--rim); }
.st-product::before { background: var(--sky); }
.name { font-size: 14px; font-weight: 600; line-height: 1.3; overflow-wrap: anywhere; }
.pin { font-size: 11px; margin-left: 4px; }
.meta { font-size: 12px; color: var(--muted); }
.warn { font-size: 12px; color: var(--cook); }
.fact { background: transparent; }
.fact .name { color: var(--muted); font-weight: 500; }
.dragging { opacity: 0.4; }
/* карандаш: предложение автоплана */
.auto { background: repeating-linear-gradient(-45deg, transparent 0 6px, var(--graphite-soft) 6px 7px), var(--enamel);
  border: 1px dashed var(--graphite); }
.auto::before { opacity: 0.45; }
.auto .name { color: var(--graphite); }
.auto.pinned { border-style: solid; }
.reason { font-size: 12px; font-style: italic; color: var(--graphite); line-height: 1.3; }
.acts { display: flex; gap: 2px; margin: 4px -4px -4px; }
.da { min-height: 32px; min-width: 32px; padding: 0 6px; border: 0; font-size: 13px; color: var(--graphite); font-weight: 400; border-radius: 8px; }
.da:hover, .da.on { background: var(--enamel-2); color: var(--ink); }
@media (hover: none) { .da { min-height: 44px; min-width: 44px; } }   /* палец, а не мышь */
@media (hover: hover) and (min-width: 700px) {
  .auto .acts { opacity: 0; transition: opacity 0.12s; }
  .auto:hover .acts, .auto:focus-within .acts { opacity: 1; }
}
</style>
