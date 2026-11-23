<script setup lang="ts">
// Окно: закрывается только явно (✕ или кнопкой в подвале); dismissible — ещё по фону и Esc
// (для окон, где только результаты поиска). Шапка и подвал закреплены, прокручивается тело.
// На телефоне — лист снизу.
import { onBeforeUnmount, onMounted } from "vue";

const props = defineProps<{ title: string; wide?: boolean; dismissible?: boolean }>();
const emit = defineEmits<{ close: [] }>();

function onKey(e: KeyboardEvent) { if (props.dismissible && e.key === "Escape") emit("close"); }
onMounted(() => { document.addEventListener("keydown", onKey); document.body.style.overflow = "hidden"; });
onBeforeUnmount(() => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; });
</script>

<template>
  <Teleport to="body">
    <div class="backdrop" @mousedown.self="dismissible && emit('close')">
      <div class="sheet" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
        <header>
          <h2>{{ title }}</h2>
          <button class="text close" aria-label="Закрыть" @click="emit('close')">✕</button>
        </header>
        <div class="body"><slot /></div>
        <footer v-if="$slots.foot"><slot name="foot" /></footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50; background: rgba(8, 14, 11, 0.5);
  display: flex; align-items: flex-start; justify-content: center; padding: 6vh 16px 16px;
}
.sheet {
  width: 100%; max-width: 560px; max-height: calc(100vh - 6vh - 16px); display: flex; flex-direction: column;
  background: var(--enamel); border: 2px solid var(--rim); border-radius: var(--r-pot); color: var(--ink);
}
.sheet.wide { max-width: 820px; }
header { display: flex; align-items: center; gap: 8px; padding: 12px 12px 10px 20px; border-bottom: 1px solid var(--line); }
h2 { flex: 1; font-size: 18px; min-width: 0; overflow-wrap: anywhere; }
.close { min-width: 44px; padding: 0; color: var(--muted); }
.body { padding: 16px 20px; overflow-y: auto; min-height: 0; flex: 1 1 auto; display: flex; flex-direction: column; gap: 14px; }
footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--line); }
@media (max-width: 600px) {
  .backdrop { padding: 0; align-items: flex-end; }
  .sheet { max-height: 92dvh; border-radius: var(--r-pot) var(--r-pot) 0 0; border-bottom: 0; }
}
</style>
