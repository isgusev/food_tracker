<script setup lang="ts">
// Иконки навигации: линии 1.8, скругления — как у остальной «эмали»
defineProps<{ name: "today" | "plan" | "shop" | "fridge" | "more" | "recipe" | "catalog" | "money" | "family" }>();
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
    <template v-else-if="name === 'recipe'">
      <!-- раскрытая книга рецептов -->
      <path d="M12 6.5C10 5 7 4.5 3.5 5v13c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5c-3.5-.5-6.5 0-8.5 1.5Z" /><path d="M12 6.5v13" />
    </template>
    <template v-else-if="name === 'catalog'">
      <path d="M4 7.5 12 4l8 3.5v9L12 20l-8-3.5v-9Z" /><path d="M4 7.5 12 11l8-3.5M12 11v9" />
    </template>
    <template v-else-if="name === 'money'">
      <rect x="3" y="6" width="18" height="12" rx="3" /><circle cx="12" cy="12" r="2.5" />
    </template>
    <template v-else-if="name === 'family'">
      <circle cx="9" cy="8.5" r="3" /><circle cx="17" cy="9.5" r="2.2" /><path d="M3.5 19c.5-3.2 2.7-5 5.5-5s5 1.8 5.5 5M15 14.2c2.6-.3 4.8 1.2 5.5 4.3" />
    </template>
    <template v-else>
      <circle cx="5.5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="18.5" cy="12" r="1.2" />
    </template>
  </svg>
</template>
