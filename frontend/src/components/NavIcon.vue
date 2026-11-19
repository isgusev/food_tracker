<script setup lang="ts">
// Иконки навигации: линии 1.8, скругления — как у остальной «эмали»
defineProps<{ name: "today" | "plan" | "shop" | "fridge" | "more" }>();
</script>

<template>
  <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8"
       stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <template v-if="name === 'today'">
      <!-- тарелка с ложкой: что едим сегодня -->
      <circle cx="11" cy="12" r="7.5" /><circle cx="11" cy="12" r="3.5" /><path d="M21 5v14" />
    </template>
    <template v-else-if="name === 'plan'">
      <rect x="3.5" y="5" width="17" height="15" rx="3" /><path d="M3.5 10h17M8 3v4M16 3v4" />
    </template>
    <template v-else-if="name === 'shop'">
      <path d="M5 8h14l-1.3 10.2a2 2 0 0 1-2 1.8H8.3a2 2 0 0 1-2-1.8L5 8Z" /><path d="M9 8V6.5a3 3 0 0 1 6 0V8" />
    </template>
    <template v-else-if="name === 'fridge'">
      <!-- кастрюля -->
      <path d="M4 10h16v6a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4v-6Z" /><path d="M2.5 10h19M9 6.5c0-1 .5-1.5 1.5-2M14 6.5c0-1 .5-1.5 1.5-2" />
    </template>
    <template v-else>
      <circle cx="5.5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="18.5" cy="12" r="1.2" />
    </template>
  </svg>
</template>
